"""Google Sheets integration via service account (matches server setup)."""

import os
import time
from datetime import datetime, timezone

from config import GOOGLE_SHEET_ID, SHEET_NAME, MAILBOX_SHEET_NAME

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Service account credential file names to search for
_SA_FILE_NAMES = ["service_account.json", "google_creds.json", "credentials.json"]

# ── Cached gspread client ────────────────────────────────────────────────────
_cached_client = None
_cached_client_time = 0

# ── Step callback (set by server.py to sync server_state) ────────────────────
_step_callback = None


def set_step_callback(cb):
    """Register a callback that receives (email, step_text) on every step update."""
    global _step_callback
    _step_callback = cb


def _find_sa_file():
    for name in _SA_FILE_NAMES:
        path = os.path.join(_BASE_DIR, name)
        if os.path.exists(path):
            return path
    return None


def get_client():
    """Return an authenticated gspread client using service account (cached 5 min)."""
    global _cached_client, _cached_client_time
    import gspread
    from google.oauth2.service_account import Credentials

    if _cached_client and (time.time() - _cached_client_time) < 300:
        return _cached_client

    sa_file = _find_sa_file()
    if not sa_file:
        raise FileNotFoundError(
            f"No Google service account file found. "
            f"Place one of {_SA_FILE_NAMES} in {_BASE_DIR}.\n"
            f"Get it from: Google Cloud Console → Service Accounts → Create Key (JSON)\n"
            f"Then share the Google Sheet with the service account email."
        )

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file(sa_file, scopes=scopes)
    _cached_client = gspread.authorize(credentials)
    _cached_client_time = time.time()
    return _cached_client


def _find_row(ws, admin_email):
    """Find the 1-indexed row number containing admin_email."""
    all_values = ws.get_all_values()
    for i, row in enumerate(all_values):
        for cell in row:
            if admin_email.lower() in str(cell).lower():
                return i + 1
    return None


def update_step(admin_email, step_text):
    """Write step progress to col H and heartbeat timestamp to col J.

    Called before each step during setup. Never raises — failures are logged
    and swallowed so they don't block the setup.
    """
    # Notify server.py callback (if registered)
    if _step_callback:
        try:
            _step_callback(admin_email, step_text)
        except Exception:
            pass

    if not GOOGLE_SHEET_ID:
        return

    try:
        gc = get_client()
        sheet = gc.open_by_key(GOOGLE_SHEET_ID)

        try:
            ws = sheet.worksheet(SHEET_NAME)
        except Exception:
            ws = sheet.sheet1

        row_found = _find_row(ws, admin_email)
        if row_found:
            heartbeat = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            ws.update_cell(row_found, 8, step_text)   # Column H = step
            ws.update_cell(row_found, 10, heartbeat)   # Column J = heartbeat
    except Exception as e:
        print(f"[sheets] update_step failed (non-blocking): {e}")


def update_tenant_credentials(admin_email, tenant_id, client_id, client_secret):
    """Find the row with admin_email and update columns E, F, G with credentials."""
    if not GOOGLE_SHEET_ID:
        print("[sheets] GOOGLE_SHEET_ID not set — skipping")
        return

    gc = get_client()
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        ws = sheet.worksheet(SHEET_NAME)
    except Exception:
        ws = sheet.sheet1

    row_found = _find_row(ws, admin_email)

    if row_found:
        ws.update_cell(row_found, 5, tenant_id)      # Column E
        ws.update_cell(row_found, 6, client_id)       # Column F
        ws.update_cell(row_found, 7, client_secret)   # Column G
        print(f"[sheets] Updated row {row_found}: E=tenant_id, F=client_id, G=client_secret")
    else:
        print(f"[sheets] Email '{admin_email}' not found in sheet — skipping update")
        print(f"[sheets] Credentials: tenant_id={tenant_id}, client_id={client_id}")


def update_status(admin_email, status, error=None):
    """Update columns H (status), I (error), J (completed_at) for the row matching admin_email."""
    if not GOOGLE_SHEET_ID:
        print("[sheets] GOOGLE_SHEET_ID not set — skipping status update")
        return

    gc = get_client()
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        ws = sheet.worksheet(SHEET_NAME)
    except Exception:
        ws = sheet.sheet1

    row_found = _find_row(ws, admin_email)

    if row_found:
        ws.update_cell(row_found, 8, status)  # Column H = status
        ws.update_cell(row_found, 9, error or "")  # Column I = error
        timestamp = datetime.now(timezone.utc).isoformat() if status in ("complete", "failed") else ""
        ws.update_cell(row_found, 10, timestamp)  # Column J = completed_at
        print(f"[sheets] Status updated for row {row_found}: {status}")
    else:
        print(f"[sheets] Email '{admin_email}' not found — skipping status update")


def read_tenants_from_sheet():
    """Read tenant credentials from the Google Sheet.

    Returns list of dicts with keys: email, password, new_password (optional).
    Reads columns B=email, C=password, D=new_password.
    """
    if not GOOGLE_SHEET_ID:
        return []

    gc = get_client()
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        ws = sheet.worksheet(SHEET_NAME)
    except Exception:
        ws = sheet.sheet1

    all_values = ws.get_all_values()
    tenants = []

    for row in all_values[1:]:  # Skip header
        if len(row) > 1 and row[1].strip():
            tenant = {
                "email": row[1].strip(),
                "password": row[2].strip() if len(row) > 2 else "",
                "new_password": row[3].strip() if len(row) > 3 else "",
            }
            if tenant["email"] and tenant["password"]:
                tenants.append(tenant)

    return tenants


# ── Mailboxes Tab ────────────────────────────────────────────────────────────
# Layout: A=# | B=Tenant Name | C=Domain | D=CF Email | E=CF API Key |
#         F=Count | G=Status | H=Step | I=Heartbeat | J=Error

def _get_mailbox_worksheet():
    """Return the Mailboxes worksheet."""
    gc = get_client()
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)
    return sheet.worksheet(MAILBOX_SHEET_NAME)


def _find_mailbox_row(ws, tenant_name):
    """Find the 1-indexed row for a tenant name in the Mailboxes tab (col B)."""
    all_values = ws.get_all_values()
    for i, row in enumerate(all_values):
        if len(row) > 1 and row[1].strip().lower() == tenant_name.strip().lower():
            return i + 1
    return None


def read_mailbox_tenants():
    """Read rows from the Mailboxes tab.

    Returns list of dicts with keys:
        tenant_name, domain, cf_email, cf_api_key, count, status.
    """
    if not GOOGLE_SHEET_ID:
        return []

    try:
        ws = _get_mailbox_worksheet()
    except Exception as e:
        print(f"[sheets] Could not open Mailboxes tab: {e}")
        return []

    all_values = ws.get_all_values()
    tenants = []

    for row in all_values[1:]:  # Skip header
        if len(row) > 1 and row[1].strip():
            tenant = {
                "tenant_name": row[1].strip(),
                "domain": row[2].strip() if len(row) > 2 else "",
                "cf_email": row[3].strip() if len(row) > 3 else "",
                "cf_api_key": row[4].strip() if len(row) > 4 else "",
                "count": int(row[5].strip()) if len(row) > 5 and row[5].strip().isdigit() else 50,
                "status": row[6].strip().lower() if len(row) > 6 else "",
            }
            tenants.append(tenant)

    return tenants


def update_mailbox_step(tenant_name, step_text):
    """Write step progress to col H and heartbeat to col I in the Mailboxes tab.

    Never raises — failures are logged and swallowed.
    """
    if not GOOGLE_SHEET_ID:
        return

    try:
        ws = _get_mailbox_worksheet()
        row = _find_mailbox_row(ws, tenant_name)
        if row:
            heartbeat = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            ws.update_cell(row, 8, step_text)    # Column H = step
            ws.update_cell(row, 9, heartbeat)     # Column I = heartbeat
    except Exception as e:
        print(f"[sheets] update_mailbox_step failed (non-blocking): {e}")


def update_mailbox_status(tenant_name, status, error=None):
    """Update col G (status) and col J (error) in the Mailboxes tab."""
    if not GOOGLE_SHEET_ID:
        return

    try:
        ws = _get_mailbox_worksheet()
        row = _find_mailbox_row(ws, tenant_name)
        if row:
            ws.update_cell(row, 7, status)                # Column G = status
            ws.update_cell(row, 10, error or "")           # Column J = error
            heartbeat = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            ws.update_cell(row, 9, heartbeat)              # Column I = heartbeat
            print(f"[sheets] Mailbox status updated for {tenant_name}: {status}")
        else:
            print(f"[sheets] Tenant '{tenant_name}' not found in Mailboxes tab")
    except Exception as e:
        print(f"[sheets] update_mailbox_status failed: {e}")


def write_generated_mailboxes(tenant_name, identities):
    """Create a per-tenant tab with the generated mailbox emails and passwords.

    Creates (or overwrites) a tab named after the tenant, e.g. "KhakiOrioleHaugh",
    with columns: # | Display Name | Email | Password
    """
    if not GOOGLE_SHEET_ID:
        return

    try:
        gc = get_client()
        sheet = gc.open_by_key(GOOGLE_SHEET_ID)

        # Create or get existing tab
        try:
            ws = sheet.worksheet(tenant_name)
            ws.clear()
        except Exception:
            ws = sheet.add_worksheet(title=tenant_name, rows=len(identities) + 1, cols=4)

        # Header
        rows = [["#", "Display Name", "Email", "Password"]]
        for i, mb in enumerate(identities, start=1):
            rows.append([i, mb["display_name"], mb["email"], mb["password"]])

        ws.update(values=rows, range_name=f"A1:D{len(rows)}")

        # Format header bold + freeze
        ws.format("A1:D1", {"textFormat": {"bold": True}})
        ws.freeze(rows=1)

        print(f"[sheets] Wrote {len(identities)} mailboxes to tab '{tenant_name}'")
    except Exception as e:
        print(f"[sheets] write_generated_mailboxes failed: {e}")
