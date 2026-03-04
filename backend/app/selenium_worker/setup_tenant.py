"""Adapted setup_tenant.py — 12-step Selenium setup with progress callback.

Removed: Google Sheets calls, file I/O
Added: progress_callback(step, message) for WebSocket relay, returns all data
"""

import logging
import time
import traceback

import requests

from app.selenium_worker.mfa_handler import find_az, do_az_login, get_graph_token, get_tenant_id
from app.selenium_worker.security_settings import run_all_security_setup
from app.selenium_worker.app_registration import (
    step_create_app, step_create_secret, step_create_service_principal,
    step_add_permissions, step_grant_admin_consent,
    step_assign_exchange_admin_role, step_upload_certificate,
)
from app.selenium_worker.cert_generator import generate_cert

logger = logging.getLogger(__name__)


def tenant_name_from_email(email: str) -> str:
    domain = email.split("@")[1]
    return domain.split(".")[0]


def setup_single_tenant(
    email: str,
    password: str,
    new_password: str = None,
    skip_login: bool = False,
    app_name: str = None,
    progress_callback=None,
    default_new_password: str = "Atoz12345@!",
) -> dict:
    """Run the full setup flow for one tenant.

    Args:
        progress_callback: callable(step: int, message: str) for progress updates
    """
    def progress(step, msg):
        logger.info(f"[Step {step}/12] {msg}")
        if progress_callback:
            progress_callback(step, msg)

    if not new_password:
        new_password = default_new_password

    tenant_name = tenant_name_from_email(email)
    result = {"admin_email": email, "admin_password": password, "status": "started"}

    step = "init"
    try:
        az_path = find_az()
        logger.info(f"Azure CLI found: {az_path}")

        # Step 1: Browser Login
        step = "login"
        progress(1, "Browser Login")
        if not skip_login:
            login_result = do_az_login(az_path, email, password, new_password)
            if login_result["password_changed"]:
                password = login_result["working_password"]
                result["admin_password"] = password
            if login_result.get("mfa_secret"):
                result["mfa_secret"] = login_result["mfa_secret"]
        else:
            logger.info("Step 1: Skipped (using existing az session)")

        # Validate login & get token
        step = "get_token"
        tenant_id = get_tenant_id(az_path)
        result["tenant_id"] = tenant_id
        token = get_graph_token(az_path)

        # Step 2: Security Setup
        step = "security"
        progress(2, "Security Setup")
        run_all_security_setup(token, tenant_id=tenant_id, az_path=az_path)

        # Step 3: Create App Registration
        step = "create_app"
        progress(3, "Create App Registration")
        name = app_name or f"{tenant_name}-automation"
        app_object_id, client_id = step_create_app(token, name)
        result["client_id"] = client_id

        # Step 4: Create Service Principal
        step = "create_sp"
        progress(4, "Create Service Principal")
        app_sp_id = step_create_service_principal(token, client_id)

        # Step 5: Create Client Secret
        step = "create_secret"
        progress(5, "Create Client Secret")
        client_secret = step_create_secret(token, app_object_id)
        result["client_secret"] = client_secret

        # Step 6: Generate & Upload Certificate
        step = "certificate"
        progress(6, "Generate Certificate")
        cert_data = generate_cert(tenant_name)
        step_upload_certificate(token, app_object_id, cert_data["cert_pem_b64"], cert_data["thumbprint"])
        result["cert_pem_b64"] = cert_data["cert_pem_b64"]
        result["cert_password"] = cert_data["pfx_password"]
        result["pfx_bytes"] = cert_data["pfx_bytes"]

        # Step 7: Add Permissions
        step = "permissions"
        progress(7, "Add API Permissions")
        graph_sp_id, graph_roles, graph_scopes, exchange_sp_id, exchange_roles = \
            step_add_permissions(token, app_object_id)

        # Step 8: Grant Admin Consent
        step = "consent"
        progress(8, "Grant Admin Consent")
        step_grant_admin_consent(
            token, app_sp_id,
            graph_sp_id, graph_roles, graph_scopes,
            exchange_sp_id, exchange_roles,
        )

        # Step 9: Assign Exchange Administrator Role
        step = "exchange_role"
        progress(9, "Assign Exchange Admin Role")
        step_assign_exchange_admin_role(token, app_sp_id)

        # Step 10: Save Credentials (no-op — saved to DB by caller)
        step = "save"
        progress(10, "Save Credentials")

        # Step 11: (Previously Google Sheet — now no-op)
        step = "post_save"
        progress(11, "Finalize")

        # Step 12: Delete MFA Authenticator
        step = "delete_mfa"
        progress(12, "Delete MFA Authenticator")
        logger.info("Waiting 30s for app permissions to propagate before MFA deletion...")
        time.sleep(30)
        try:
            _delete_mfa(tenant_id, client_id, client_secret, email, graph_token=token)
        except Exception as e:
            logger.warning(f"MFA deletion failed: {e}")

        result["status"] = "complete"
        logger.info(f"SETUP COMPLETE for {tenant_name}")

    except Exception as e:
        result["status"] = f"failed_at_{step}"
        result["error"] = str(e)
        logger.error(f"Failed at step '{step}': {e}")
        traceback.print_exc()

    return result


def _delete_mfa(tenant_id, client_id, client_secret, admin_email, graph_token=None):
    """Delete all MFA authenticator methods for the admin user via Graph API."""
    graph = "https://graph.microsoft.com/v1.0"

    def _get_client_token():
        r = requests.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": client_id, "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }, timeout=30,
        )
        return r.json().get("access_token")

    def _try_delete(token):
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        r = requests.get(f"{graph}/users/{admin_email}", headers=headers, timeout=30)
        if r.status_code == 403:
            return 0, True
        if r.status_code != 200:
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
            r = requests.get(f"{graph}/users/{user_id}/authentication/{endpoint}",
                             headers=headers, timeout=30)
            if r.status_code == 403:
                saw_403 = True
                continue
            if r.status_code == 200:
                for method in r.json().get("value", []):
                    dr = requests.delete(
                        f"{graph}/users/{user_id}/authentication/{endpoint}/{method['id']}",
                        headers=headers, timeout=30,
                    )
                    if dr.status_code == 204:
                        logger.info(f"Deleted {label} method: {method['id']}")
                        deleted += 1
        return deleted, saw_403

    if graph_token:
        deleted, got_403 = _try_delete(graph_token)
        if deleted > 0:
            return
        if not got_403:
            return

    backoff = [0, 30, 60, 90]
    for i, wait in enumerate(backoff):
        if wait > 0:
            logger.info(f"Waiting {wait}s for permissions to propagate (attempt {i + 1})...")
            time.sleep(wait)
        token = _get_client_token()
        if not token:
            return
        deleted, got_403 = _try_delete(token)
        if deleted > 0 or not got_403:
            return

    logger.warning("MFA deletion failed — permissions did not propagate in time")
