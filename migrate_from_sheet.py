"""One-time migration: read tenant credentials from Google Sheet → insert into Postgres."""

import json
import sys
import uuid
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials
import psycopg2
from cryptography.fernet import Fernet

# ── Config ──────────────────────────────────────────────────────────────
SHEET_ID = "15Acf8eoUirAyNGs-i-Nxx2DTigOzRbod882ma16JeO8"
SHEET_NAME = "Settings"
SA_FILE = "service_account.json"

# Read from .env
import os
from dotenv import load_dotenv
load_dotenv()

DB_URL = os.getenv("DATABASE_URL_SYNC", "postgresql://tenantadmin:dbpass@localhost:5432/tenants")
FERNET_KEY = os.getenv("FERNET_KEY")

if not FERNET_KEY:
    print("ERROR: FERNET_KEY not set in .env")
    sys.exit(1)

fernet = Fernet(FERNET_KEY.encode())


def encrypt(plaintext: str) -> bytes:
    return fernet.encrypt(plaintext.encode())


def main():
    # Connect to Google Sheets
    print("Connecting to Google Sheets...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(SA_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(SHEET_ID)

    try:
        ws = sheet.worksheet(SHEET_NAME)
    except Exception:
        ws = sheet.sheet1

    rows = ws.get_all_values()
    headers = rows[0] if rows else []
    data_rows = rows[1:]

    print(f"Found {len(data_rows)} rows in sheet (headers: {headers})")

    # Sheet layout: A=tenant_name, B=email, C=password, D=new_password,
    #               E=tenant_id, F=client_id, G=client_secret, H=status, I=error, J=completed_at

    # Connect to Postgres
    print(f"Connecting to database...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # Check existing tenants
    cur.execute("SELECT admin_email FROM tenants")
    existing = {row[0].lower() for row in cur.fetchall()}
    print(f"Already have {len(existing)} tenants in DB")

    migrated = 0
    skipped = 0

    for i, row in enumerate(data_rows, start=2):
        # Pad row to at least 10 columns
        while len(row) < 10:
            row.append("")

        tenant_name = row[0].strip()
        email = row[1].strip()
        password = row[2].strip()
        new_password = row[3].strip()
        tenant_id_ms = row[4].strip()
        client_id = row[5].strip()
        client_secret = row[6].strip()
        status = row[7].strip().lower()
        error = row[8].strip()
        completed_at = row[9].strip()

        if not email:
            continue

        if email.lower() in existing:
            print(f"  SKIP row {i}: {email} (already exists)")
            skipped += 1
            continue

        # Map sheet status to DB status
        db_status = {
            "complete": "completed",
            "done": "completed",
            "failed": "failed",
            "running": "failed",  # stale running = treat as failed
            "pending": "pending",
        }.get(status, "pending")

        # Parse completed_at
        db_completed_at = None
        if completed_at and db_status == "completed":
            try:
                db_completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            except Exception:
                db_completed_at = datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        tid = str(uuid.uuid4())

        cur.execute("""
            INSERT INTO tenants (
                id, name, admin_email, admin_password, new_password,
                tenant_id_ms, client_id, client_secret,
                mfa_secret, cert_pfx, cert_password,
                status, current_step, error_message,
                created_at, updated_at, completed_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            )
        """, (
            tid,
            tenant_name,
            email,
            encrypt(password) if password else None,
            encrypt(new_password) if new_password else None,
            encrypt(tenant_id_ms) if tenant_id_ms else None,
            encrypt(client_id) if client_id else None,
            encrypt(client_secret) if client_secret else None,
            None,  # mfa_secret — not in sheet
            None,  # cert_pfx
            None,  # cert_password
            db_status,
            None,  # current_step
            error if error else None,
            now,
            now,
            db_completed_at,
        ))

        print(f"  OK  row {i}: {tenant_name} <{email}> status={db_status}")
        migrated += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nDone! Migrated: {migrated}, Skipped: {skipped}, Total in sheet: {len(data_rows)}")


if __name__ == "__main__":
    main()
