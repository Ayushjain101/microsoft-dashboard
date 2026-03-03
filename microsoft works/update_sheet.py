"""
Update Google Sheet with Azure credentials.
Finds the row with admin email and updates columns E, F, G with Tenant ID, Client ID, Client Secret.
"""

import os
import sys
import json

def load_env():
    """Load .env file."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    env[key.strip()] = val.strip()
    return env

def main():
    # Load credentials from .env
    env = load_env()
    
    tenant_id = env.get("TENANT_ID", "")
    client_id = env.get("CLIENT_ID", "")
    client_secret = env.get("CLIENT_SECRET", "")
    admin_email = env.get("ADMIN_EMAIL", "")
    
    # Sheet ID from your Google Sheet URL
    sheet_id = "1fuwvD1G0zlTpLc5pF0bPOnEMnIBa65StVcXww3cJQ-M"
    
    if not all([tenant_id, client_id, client_secret, admin_email]):
        print("[ERROR] Missing credentials in .env file")
        print("       Run setup_azure_app.ps1 first")
        sys.exit(1)
    
    print(f"[INFO] Admin Email: {admin_email}")
    print(f"[INFO] Tenant ID: {tenant_id}")
    print(f"[INFO] Client ID: {client_id}")
    print(f"[INFO] Sheet ID: {sheet_id}")
    print()
    
    # Check if gspread is available
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("[ERROR] gspread not installed")
        print("        Run: pip install gspread google-auth")
        sys.exit(1)
    
    # Find Google service account credentials
    sa_file = None
    for f in ['service_account.json', 'google_creds.json', 'credentials.json']:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f)
        if os.path.exists(path):
            sa_file = path
            break
    
    if not sa_file:
        print("[ERROR] No Google service account file found")
        print("        Create one of these files:")
        print("        - service_account.json")
        print("        - google_creds.json")
        print("        - credentials.json")
        print()
        print("        Get it from Google Cloud Console:")
        print("        1. Go to console.cloud.google.com")
        print("        2. Create a project (or use existing)")
        print("        3. Enable Google Sheets API")
        print("        4. Create Service Account")
        print("        5. Create Key (JSON) and download")
        print("        6. Save as service_account.json in this folder")
        print("        7. Share your Google Sheet with the service account email")
        sys.exit(1)
    
    print(f"[INFO] Using: {sa_file}")
    
    # Connect to Google Sheets
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        credentials = Credentials.from_service_account_file(sa_file, scopes=scopes)
        gc = gspread.authorize(credentials)
        print("[OK] Connected to Google Sheets")
    except Exception as e:
        print(f"[ERROR] Failed to connect: {e}")
        sys.exit(1)
    
    # Open sheet
    try:
        sheet = gc.open_by_key(sheet_id)
        print(f"[OK] Opened sheet: {sheet.title}")
    except Exception as e:
        print(f"[ERROR] Failed to open sheet: {e}")
        print("        Make sure you shared the sheet with the service account email")
        sys.exit(1)
    
    # Try Settings tab first, then first sheet
    try:
        ws = sheet.worksheet('Settings')
        print(f"[OK] Using worksheet: Settings")
    except:
        ws = sheet.sheet1
        print(f"[OK] Using worksheet: {ws.title}")
    
    # Get all values
    all_values = ws.get_all_values()
    print(f"[INFO] Found {len(all_values)} rows")
    
    # Find row with admin email (check all columns)
    row_found = None
    for i, row in enumerate(all_values):
        for j, cell in enumerate(row):
            if admin_email.lower() in str(cell).lower():
                row_found = i + 1  # 1-indexed
                print(f"[OK] Found admin email in row {row_found}, column {j + 1}")
                break
        if row_found:
            break
    
    if row_found:
        # Update columns E, F, G (5, 6, 7)
        print(f"[INFO] Updating row {row_found}...")
        ws.update_cell(row_found, 5, tenant_id)     # Column E = TENANT_ID
        ws.update_cell(row_found, 6, client_id)     # Column F = CLIENT_ID
        ws.update_cell(row_found, 7, client_secret) # Column G = CLIENT_SECRET
        print(f"[OK] Updated columns E, F, G in row {row_found}")
        print()
        print("============================================================")
        print("  SHEET UPDATED SUCCESSFULLY!")
        print("============================================================")
        print(f"  Row: {row_found}")
        print(f"  Column E (TENANT_ID): {tenant_id}")
        print(f"  Column F (CLIENT_ID): {client_id}")
        print(f"  Column G (CLIENT_SECRET): {client_secret[:10]}...")
        print("============================================================")
    else:
        print(f"[WARN] Admin email '{admin_email}' not found in sheet")
        print()
        print("Options:")
        print("  1. Add the admin email to your sheet first")
        print("  2. Manually paste credentials into columns E, F, G")
        print()
        print("Credentials to paste:")
        print(f"  TENANT_ID:     {tenant_id}")
        print(f"  CLIENT_ID:     {client_id}")
        print(f"  CLIENT_SECRET: {client_secret}")


if __name__ == "__main__":
    main()

