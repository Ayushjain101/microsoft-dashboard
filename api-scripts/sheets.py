"""Google Sheets integration for the API pipeline."""

import os
from datetime import datetime, timezone

from config import GOOGLE_SHEET_ID, PIPELINE_SHEET_NAME

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Service account credential file names to search for
_SA_FILE_NAMES = ["service_account.json", "google_creds.json", "credentials.json"]

# Expected headers for the Pipeline tab
_PIPELINE_HEADERS = [
    "tenant_name", "domain", "status", "current_step",
    "mailbox_count", "error", "started_at", "completed_at",
]


def _find_sa_file():
    """Search for service account JSON in api-scripts/ then selenium-setup/ (fallback)."""
    for name in _SA_FILE_NAMES:
        # Check api-scripts/ first
        path = os.path.join(_BASE_DIR, name)
        if os.path.exists(path):
            return path
        # Fallback to selenium-setup/
        fallback = os.path.join(_BASE_DIR, "..", "selenium-setup", name)
        if os.path.exists(fallback):
            return os.path.abspath(fallback)
    return None


def get_client():
    """Return an authenticated gspread client using service account."""
    import gspread
    from google.oauth2.service_account import Credentials

    sa_file = _find_sa_file()
    if not sa_file:
        raise FileNotFoundError(
            f"No Google service account file found. "
            f"Place one of {_SA_FILE_NAMES} in {_BASE_DIR} "
            f"or in ../selenium-setup/.\n"
            f"Get it from: Google Cloud Console → Service Accounts → Create Key (JSON)\n"
            f"Then share the Google Sheet with the service account email."
        )

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file(sa_file, scopes=scopes)
    return gspread.authorize(credentials)


def ensure_pipeline_headers():
    """Create the Pipeline tab with headers if it doesn't exist."""
    gc = get_client()
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        ws = sheet.worksheet(PIPELINE_SHEET_NAME)
    except Exception:
        ws = sheet.add_worksheet(title=PIPELINE_SHEET_NAME, rows=100, cols=len(_PIPELINE_HEADERS))
        ws.update(range_name="A1", values=[_PIPELINE_HEADERS])
        print(f"[sheets] Created '{PIPELINE_SHEET_NAME}' tab with headers")
        return ws

    # Tab exists — ensure headers are present
    first_row = ws.row_values(1)
    if not first_row or first_row[0] != _PIPELINE_HEADERS[0]:
        ws.update(range_name="A1", values=[_PIPELINE_HEADERS])
        print(f"[sheets] Updated headers in '{PIPELINE_SHEET_NAME}' tab")

    return ws


def read_tenants_from_sheet():
    """Read tenants from the Pipeline tab where status is 'pending'.

    Returns list of dicts: {tenant_name, domain, mailbox_count}
    """
    if not GOOGLE_SHEET_ID:
        return []

    gc = get_client()
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        ws = sheet.worksheet(PIPELINE_SHEET_NAME)
    except Exception:
        print(f"[sheets] '{PIPELINE_SHEET_NAME}' tab not found")
        return []

    all_values = ws.get_all_values()
    tenants = []

    for row in all_values[1:]:  # Skip header
        if len(row) < 3:
            continue
        tenant_name = row[0].strip()
        domain = row[1].strip() if len(row) > 1 else ""
        status = row[2].strip().lower() if len(row) > 2 else ""
        mailbox_count = row[4].strip() if len(row) > 4 else ""

        if tenant_name and status == "pending":
            tenants.append({
                "tenant_name": tenant_name,
                "domain": domain,
                "mailbox_count": int(mailbox_count) if mailbox_count.isdigit() else 50,
            })

    return tenants


def update_pipeline_status(tenant_name, status, current_step=None, error=None):
    """Update the Pipeline tab row matching tenant_name with status, step, error, timestamps."""
    if not GOOGLE_SHEET_ID:
        print("[sheets] GOOGLE_SHEET_ID not set — skipping")
        return

    gc = get_client()
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        ws = sheet.worksheet(PIPELINE_SHEET_NAME)
    except Exception:
        print(f"[sheets] '{PIPELINE_SHEET_NAME}' tab not found — skipping")
        return

    all_values = ws.get_all_values()

    # Find row matching tenant_name (column A)
    row_found = None
    for i, row in enumerate(all_values):
        if row and row[0].strip().lower() == tenant_name.strip().lower():
            row_found = i + 1  # 1-indexed
            break

    if not row_found:
        print(f"[sheets] Tenant '{tenant_name}' not found in Pipeline tab — skipping")
        return

    now = datetime.now(timezone.utc).isoformat()

    ws.update_cell(row_found, 3, status)  # Column C = status
    if current_step is not None:
        ws.update_cell(row_found, 4, current_step)  # Column D = current_step
    ws.update_cell(row_found, 6, error or "")  # Column F = error

    if status == "running":
        ws.update_cell(row_found, 7, now)  # Column G = started_at
    if status in ("done", "failed"):
        ws.update_cell(row_found, 8, now)  # Column H = completed_at

    print(f"[sheets] Pipeline status for '{tenant_name}': {status}" +
          (f" (step: {current_step})" if current_step else ""))
