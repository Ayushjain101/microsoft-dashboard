#!/usr/bin/env python3
"""
setup_tenant.py — One-time Microsoft 365 tenant setup
======================================================
Uses az login (device code flow + Selenium) then Graph API for everything.

Usage:
  python setup_tenant.py --email admin@Tenant.onmicrosoft.com --password 'Pass'
  python setup_tenant.py --email admin@x.onmicrosoft.com --password 'Old' --new-password 'New!'
  python setup_tenant.py --sheet          (read from Google Sheet)
  python setup_tenant.py --skip-login     (use existing az session)
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime

from mfa_handler import find_az, do_az_login, get_graph_token, get_tenant_id, info, ok, warn
from security_settings import run_all_security_setup
from app_registration import (
    step_create_app,
    step_create_secret,
    step_create_service_principal,
    step_add_permissions,
    step_grant_admin_consent,
    step_assign_exchange_admin_role,
    step_upload_certificate,
)
from cert_generator import generate_cert
from sheets import update_tenant_credentials, update_status, update_step, read_tenants_from_sheet

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def tenant_name_from_email(email: str) -> str:
    domain = email.split("@")[1]
    return domain.split(".")[0]


def setup_single_tenant(
    email: str,
    password: str,
    new_password: str = None,
    skip_login: bool = False,
    app_name: str = None,
) -> dict:
    """Run the full setup flow for one tenant."""
    tenant_name = tenant_name_from_email(email)
    result = {"admin_email": email, "admin_password": password, "status": "started"}

    print()
    print("=" * 60)
    print(f"  Setting up tenant: {tenant_name}")
    print(f"  Admin: {email}")
    print("=" * 60)
    print()

    step = "init"
    try:
        # ── Find Azure CLI ────────────────────────────────────────────
        az_path = find_az()
        ok(f"Azure CLI found: {az_path}")

        # ── Step 1: Browser Login via device code ─────────────────────
        step = "login"
        try: update_step(email, "Step 1/12: Browser Login")
        except Exception: pass
        if not skip_login:
            info("Step 1: Browser Login")
            info("-" * 40)
            login_result = do_az_login(az_path, email, password, new_password)
            if login_result["password_changed"]:
                password = login_result["working_password"]
                result["admin_password"] = password
                ok(f"Password was changed. Working password saved.")
        else:
            info("Step 1: Skipped (using existing az session)")
        print()

        # ── Validate login & get token ────────────────────────────────
        step = "get_token"
        tenant_id = get_tenant_id(az_path)
        ok(f"Logged in — Tenant: {tenant_id}")
        result["tenant_id"] = tenant_id

        token = get_graph_token(az_path)
        ok("Graph API token acquired")
        print()

        # ── Step 2: Security Setup ────────────────────────────────────
        step = "security"
        try: update_step(email, "Step 2/12: Security Setup")
        except Exception: pass
        info("Step 2: Security Setup")
        info("-" * 40)
        run_all_security_setup(token, tenant_id=tenant_id, az_path=az_path)
        print()

        # ── Step 3: Create App Registration ───────────────────────────
        step = "create_app"
        try: update_step(email, "Step 3/12: Create App Registration")
        except Exception: pass
        info("Step 3: Create App Registration")
        info("-" * 40)
        name = app_name or f"{tenant_name}-automation"
        app_object_id, client_id = step_create_app(token, name)
        result["client_id"] = client_id
        print()

        # ── Step 4: Create Service Principal ──────────────────────────
        step = "create_sp"
        try: update_step(email, "Step 4/12: Create Service Principal")
        except Exception: pass
        info("Step 4: Create Service Principal")
        info("-" * 40)
        app_sp_id = step_create_service_principal(token, client_id)
        print()

        # ── Step 5: Create Client Secret ──────────────────────────────
        step = "create_secret"
        try: update_step(email, "Step 5/12: Create Client Secret")
        except Exception: pass
        info("Step 5: Create Client Secret")
        info("-" * 40)
        client_secret = step_create_secret(token, app_object_id)
        result["client_secret"] = client_secret
        print()

        # ── Step 6: Generate & Upload Certificate ─────────────────────
        step = "certificate"
        try: update_step(email, "Step 6/12: Generate Certificate")
        except Exception: pass
        info("Step 6: Generate & Upload Certificate")
        info("-" * 40)
        cert_data = generate_cert(tenant_name)
        step_upload_certificate(token, app_object_id, cert_data["cert_pem_b64"], cert_data["thumbprint"])
        result["cert_base64"] = cert_data["cert_pem_b64"]
        result["cert_password"] = cert_data["pfx_password"]
        print()

        # ── Step 7: Add Permissions ───────────────────────────────────
        step = "permissions"
        try: update_step(email, "Step 7/12: Add API Permissions")
        except Exception: pass
        info("Step 7: Add API Permissions")
        info("-" * 40)
        graph_sp_id, graph_roles, graph_scopes, exchange_sp_id, exchange_roles = \
            step_add_permissions(token, app_object_id)
        print()

        # ── Step 8: Grant Admin Consent ───────────────────────────────
        step = "consent"
        try: update_step(email, "Step 8/12: Grant Admin Consent")
        except Exception: pass
        info("Step 8: Grant Admin Consent")
        info("-" * 40)
        step_grant_admin_consent(
            token, app_sp_id,
            graph_sp_id, graph_roles, graph_scopes,
            exchange_sp_id, exchange_roles,
        )
        print()

        # ── Step 9: Assign Exchange Administrator Role ────────────────
        step = "exchange_role"
        try: update_step(email, "Step 9/12: Assign Exchange Admin Role")
        except Exception: pass
        info("Step 9: Assign Exchange Administrator Role")
        info("-" * 40)
        step_assign_exchange_admin_role(token, app_sp_id)
        print()

        # ── Step 10: Save to .env ─────────────────────────────────────
        step = "save_env"
        try: update_step(email, "Step 10/12: Save Credentials")
        except Exception: pass
        info("Step 10: Save Credentials")
        info("-" * 40)
        _save_env(tenant_name, tenant_id, client_id, client_secret, email)
        _save_backup_json(tenant_name, result)
        print()

        # ── Step 11: Update Google Sheet ──────────────────────────────
        step = "sheets"
        try: update_step(email, "Step 11/12: Update Google Sheet")
        except Exception: pass
        info("Step 11: Update Google Sheet")
        info("-" * 40)
        try:
            update_tenant_credentials(email, tenant_id, client_id, client_secret)
        except Exception as e:
            warn(f"Google Sheets update failed: {e}")
            info("Credentials saved locally in .env and output/ — you can update the sheet manually.")
        print()

        # ── Step 12: Delete MFA Authenticator ────────────────────────
        step = "delete_mfa"
        try: update_step(email, "Step 12/12: Delete MFA Authenticator")
        except Exception: pass
        info("Step 12: Delete MFA Authenticator")
        info("-" * 40)
        info("Waiting 30s for app permissions to propagate before MFA deletion...")
        time.sleep(30)
        try:
            _delete_mfa(tenant_id, client_id, client_secret, email, graph_token=token)
        except Exception as e:
            warn(f"MFA deletion failed: {e}")
            info("You can delete it manually from mysignins.microsoft.com/security-info")
        print()

        result["status"] = "complete"

        # Save final credentials with status=complete
        _save_backup_json(tenant_name, result)

        try:
            update_status(email, "complete")
        except Exception:
            pass

        # ── Summary ───────────────────────────────────────────────────
        print("=" * 60)
        ok("  SETUP COMPLETE!")
        print("=" * 60)
        print()
        info(f"  Tenant ID:     {tenant_id}")
        info(f"  Client ID:     {client_id}")
        info(f"  Client Secret: {client_secret[:10]}...")
        info(f"  App Name:      {name}")
        print()
        info("  Next: Run the tenant setup automation:")
        info("    python tenant_setup_automation.py --use-cli")
        print("=" * 60)
        print()

    except Exception as e:
        result["status"] = f"failed_at_{step}"
        result["error"] = str(e)
        print(f"\n[ERROR] Failed at step '{step}': {e}")
        traceback.print_exc()
        _save_backup_json(tenant_name, result)
        try:
            update_status(email, "failed", error=str(e))
        except Exception:
            pass

    return result


def _delete_mfa(tenant_id, client_id, client_secret, admin_email, graph_token=None):
    """Delete all MFA authenticator methods for the admin user via Graph API.

    Uses client credentials token. The app's UserAuthenticationMethod.ReadWrite.All
    permission may take a few minutes to propagate after creation, so this function
    retries with backoff if the first attempt gets 403.
    """
    import requests

    graph = "https://graph.microsoft.com/v1.0"

    def _get_client_token():
        r = requests.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        return r.json().get("access_token")

    def _try_delete(token):
        """Attempt to list and delete MFA methods. Returns (deleted_count, got_403)."""
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        r = requests.get(f"{graph}/users/{admin_email}", headers=headers)
        if r.status_code == 403:
            return 0, True
        if r.status_code != 200:
            warn(f"Could not find user {admin_email}: {r.status_code}")
            return 0, False
        user_id = r.json()["id"]

        deleted = 0
        saw_403 = False
        method_types = [
            ("microsoftAuthenticatorMethods", "Authenticator"),
            ("softwareOathMethods", "TOTP"),
            ("phoneMethods", "Phone"),
        ]

        for endpoint, label in method_types:
            r = requests.get(f"{graph}/users/{user_id}/authentication/{endpoint}", headers=headers)
            if r.status_code == 403:
                saw_403 = True
                continue
            if r.status_code == 200:
                for method in r.json().get("value", []):
                    dr = requests.delete(
                        f"{graph}/users/{user_id}/authentication/{endpoint}/{method['id']}",
                        headers=headers,
                    )
                    if dr.status_code == 204:
                        ok(f"Deleted {label} method: {method['id']}")
                        deleted += 1
                    else:
                        warn(f"Failed to delete {label} method {method['id']}: {dr.status_code}")

        return deleted, saw_403

    # Try with delegated token first (if provided)
    if graph_token:
        deleted, got_403 = _try_delete(graph_token)
        if deleted > 0:
            ok(f"Deleted {deleted} MFA method(s)")
            return
        if not got_403:
            info("No MFA methods found to delete")
            return

    # Use client credentials with retry for permission propagation
    backoff = [0, 30, 60, 90]
    for i, wait in enumerate(backoff):
        if wait > 0:
            info(f"Waiting {wait}s for app permissions to propagate (attempt {i + 1}/{len(backoff)})...")
            time.sleep(wait)

        token = _get_client_token()
        if not token:
            warn("Could not get client credentials token")
            return

        deleted, got_403 = _try_delete(token)
        if deleted > 0:
            ok(f"Deleted {deleted} MFA method(s)")
            return
        if not got_403:
            info("No MFA methods found to delete")
            return

    warn("MFA deletion failed — permissions did not propagate in time")
    info("Delete manually at: https://mysignins.microsoft.com/security-info")


def _save_env(tenant_name, tenant_id, client_id, client_secret, admin_email=""):
    """Save credentials to per-tenant .env file inside output/{tenant_name}/."""
    out_dir = os.path.join(BASE_DIR, "output", tenant_name)
    os.makedirs(out_dir, exist_ok=True)
    env_path = os.path.join(out_dir, ".env")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# Azure App Registration credentials\n")
        f.write(f"TENANT_ID={tenant_id}\n")
        f.write(f"CLIENT_ID={client_id}\n")
        f.write(f"CLIENT_SECRET={client_secret}\n")
        if admin_email:
            f.write(f"ADMIN_EMAIL={admin_email}\n")

    ok(f"Credentials saved to {env_path}")


def _save_backup_json(tenant_name, data):
    """Write credentials to output/{tenant_name}/credentials.json and output/{tenant_name}.json."""
    out_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(out_dir, exist_ok=True)

    # Per-tenant subdirectory (primary — used by tenant_loader)
    tenant_dir = os.path.join(out_dir, tenant_name)
    os.makedirs(tenant_dir, exist_ok=True)
    sub_path = os.path.join(tenant_dir, "credentials.json")
    with open(sub_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    # Flat file (kept for backward compatibility with tenant_loader)
    flat_path = os.path.join(out_dir, f"{tenant_name}.json")
    with open(flat_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    ok(f"Credentials saved to {sub_path} (and {flat_path})")


def main():
    parser = argparse.ArgumentParser(
        description="One-time Microsoft 365 tenant setup (device code + Graph API)"
    )
    parser.add_argument("--email", help="Admin email (admin@Tenant.onmicrosoft.com)")
    parser.add_argument("--password", help="Admin password")
    parser.add_argument("--new-password", default=None, help="New password if forced to change")
    parser.add_argument("--app-name", default=None, help="App registration name")
    parser.add_argument("--skip-login", action="store_true", help="Skip login (use existing az session)")
    parser.add_argument("--sheet", action="store_true", help="Read credentials from Google Sheet")
    parser.add_argument("--csv", help="CSV file with columns: email, password")

    args = parser.parse_args()

    if args.sheet:
        # Batch from Google Sheet
        tenants = read_tenants_from_sheet()
        if not tenants:
            print("[ERROR] No tenants found in Google Sheet")
            sys.exit(1)
        results = []
        for t in tenants:
            result = setup_single_tenant(t["email"], t["password"], t.get("new_password"))
            results.append(result)
        _print_batch_summary(results)

    elif args.csv:
        # Batch from CSV
        import csv
        results = []
        with open(args.csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get("email", "").strip()
                password = row.get("password", "").strip()
                new_password = row.get("new_password", "").strip()
                # If no new_password specified, use standard password for forced change
                if not new_password:
                    new_password = "Atoz12345@!"
                if email and password:
                    result = setup_single_tenant(email, password, new_password)
                    results.append(result)
        _print_batch_summary(results)

    elif args.skip_login:
        # Use existing az session — still need email for naming
        email = args.email or "admin@tenant.onmicrosoft.com"
        setup_single_tenant(email, "", skip_login=True, app_name=args.app_name)

    elif args.email and args.password:
        new_pw = args.new_password or "Atoz12345@!"
        setup_single_tenant(args.email, args.password, new_pw, app_name=args.app_name)

    else:
        parser.print_help()
        sys.exit(1)


def _print_batch_summary(results):
    ok_count = sum(1 for r in results if r["status"] == "complete")
    fail_count = len(results) - ok_count
    print(f"\n[batch] Done: {ok_count} succeeded, {fail_count} failed out of {len(results)}")


if __name__ == "__main__":
    main()
