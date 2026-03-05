"""Adapted setup_tenant.py — 13-step Selenium setup with progress callback.

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
    mfa_secret: str = None,
    skip_login: bool = False,
    app_name: str = None,
    progress_callback=None,
    step_result_callback=None,
    default_new_password: str = "Atoz12345@!",
    on_mfa_secret=None,
) -> dict:
    """Run the full setup flow for one tenant.

    Args:
        progress_callback: callable(step: int, message: str) for progress updates
        step_result_callback: callable(step: int, status: str, detail: str|None) for step results
    """
    def progress(step, msg):
        logger.info(f"[Step {step}/13] {msg}")
        if progress_callback:
            progress_callback(step, msg)

    def record_step(step, status, detail=None):
        if step_result_callback:
            step_result_callback(step, status, detail)

    if not new_password:
        new_password = default_new_password

    tenant_name = tenant_name_from_email(email)
    result = {"admin_email": email, "admin_password": password, "status": "started"}

    # Map step labels to numbers for failed_step tracking
    STEP_MAP = {
        "init": 0, "login": 1, "get_token": 1, "security": 2, "create_app": 3,
        "create_sp": 4, "create_secret": 5, "certificate": 6, "permissions": 7,
        "consent": 8, "exchange_role": 9, "save": 10, "post_save": 11,
        "instantly_consent": 12, "delete_mfa": 13,
    }

    step = "init"
    try:
        az_path = find_az()
        logger.info(f"Azure CLI found: {az_path}")

        # Step 1: Browser Login
        step = "login"
        progress(1, "Browser Login")
        if not skip_login:
            login_result = do_az_login(az_path, email, password, new_password, mfa_secret=mfa_secret, on_mfa_secret=on_mfa_secret)
            if login_result["password_changed"]:
                password = login_result["working_password"]
                result["admin_password"] = password
            if login_result.get("mfa_secret"):
                result["mfa_secret"] = login_result["mfa_secret"]
        else:
            logger.info("Step 1: Skipped (using existing az session)")
        record_step(1, "success")

        # Validate login & get token
        step = "get_token"
        tenant_id = get_tenant_id(az_path)
        result["tenant_id"] = tenant_id
        token = get_graph_token(az_path)

        # Step 2: Security Setup
        step = "security"
        progress(2, "Security Setup")
        run_all_security_setup(token, tenant_id=tenant_id, az_path=az_path)
        record_step(2, "success")

        # Step 3: Create App Registration
        step = "create_app"
        progress(3, "Create App Registration")
        name = app_name or f"{tenant_name}-automation"
        app_object_id, client_id = step_create_app(token, name)
        result["client_id"] = client_id
        record_step(3, "success")

        # Step 4: Create Service Principal
        step = "create_sp"
        progress(4, "Create Service Principal")
        app_sp_id = step_create_service_principal(token, client_id)
        record_step(4, "success")

        # Step 5: Create Client Secret
        step = "create_secret"
        progress(5, "Create Client Secret")
        client_secret = step_create_secret(token, app_object_id)
        result["client_secret"] = client_secret
        record_step(5, "success")

        # Step 6: Generate & Upload Certificate
        step = "certificate"
        progress(6, "Generate Certificate")
        cert_data = generate_cert(tenant_name)
        step_upload_certificate(token, app_object_id, cert_data["cert_pem_b64"], cert_data["thumbprint"])
        result["cert_pem_b64"] = cert_data["cert_pem_b64"]
        result["cert_password"] = cert_data["pfx_password"]
        result["pfx_bytes"] = cert_data["pfx_bytes"]
        record_step(6, "success")

        # Step 7: Add Permissions
        step = "permissions"
        progress(7, "Add API Permissions")
        graph_sp_id, graph_roles, graph_scopes, exchange_sp_id, exchange_roles = \
            step_add_permissions(token, app_object_id)
        record_step(7, "success")

        # Step 8: Grant Admin Consent
        step = "consent"
        progress(8, "Grant Admin Consent")
        step_grant_admin_consent(
            token, app_sp_id,
            graph_sp_id, graph_roles, graph_scopes,
            exchange_sp_id, exchange_roles,
        )
        record_step(8, "success")

        # Step 9: Assign Exchange Administrator Role
        step = "exchange_role"
        progress(9, "Assign Exchange Admin Role")
        step_assign_exchange_admin_role(token, app_sp_id)
        record_step(9, "success")

        # Step 10: Save Credentials (no-op — saved to DB by caller)
        step = "save"
        progress(10, "Save Credentials")
        record_step(10, "success")

        # Step 11: Retry security setup with app credentials
        step = "post_save"
        progress(11, "Finalize")
        try:
            logger.info("Retrying security setup with app client credentials...")
            time.sleep(15)  # Wait for permissions to propagate
            app_token = _get_app_token(tenant_id, client_id, client_secret)
            if app_token:
                from app.selenium_worker.security_settings import (
                    disable_security_defaults, disable_mfa_registration_campaign,
                    disable_system_preferred_mfa, enable_smtp_auth_org,
                )
                disable_security_defaults(app_token)
                disable_mfa_registration_campaign(app_token)
                disable_system_preferred_mfa(app_token)
                enable_smtp_auth_org(app_token, tenant_id=tenant_id, az_path=az_path)
            else:
                logger.warning("Could not get app token for security retry")
            record_step(11, "success")
        except Exception as e:
            logger.warning(f"Security retry with app credentials failed: {e}")
            record_step(11, "warning", str(e))

        # Step 12: Grant Instantly (third-party) Admin Consent
        step = "instantly_consent"
        progress(12, "Grant Instantly Admin Consent")
        try:
            _app_token = app_token if app_token else _get_app_token(tenant_id, client_id, client_secret)
            if _app_token:
                _grant_instantly_consent(_app_token)
            record_step(12, "success")
        except Exception as e:
            logger.warning(f"Instantly consent failed (non-fatal): {e}")
            record_step(12, "warning", str(e))

        # Step 13: Delete MFA Authenticator
        step = "delete_mfa"
        progress(13, "Delete MFA Authenticator")
        logger.info("Waiting 30s for app permissions to propagate before MFA deletion...")
        time.sleep(30)
        try:
            _delete_mfa(tenant_id, client_id, client_secret, email, graph_token=token)
            record_step(13, "success")
        except Exception as e:
            logger.warning(f"MFA deletion failed: {e}")
            record_step(13, "warning", str(e))

        result["status"] = "complete"
        logger.info(f"SETUP COMPLETE for {tenant_name}")

    except Exception as e:
        result["status"] = f"failed_at_{step}"
        result["error"] = str(e)
        result["failed_step"] = STEP_MAP.get(step, 0)
        logger.error(f"Failed at step '{step}': {e}")
        traceback.print_exc()

    return result


def _get_app_token(tenant_id, client_id, client_secret):
    """Get a client credentials token for the app registration."""
    r = requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "client_id": client_id, "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }, timeout=30,
    )
    return r.json().get("access_token")


def _delete_mfa(tenant_id, client_id, client_secret, admin_email, graph_token=None):
    """Delete all MFA authenticator methods for the admin user via Graph API."""
    graph = "https://graph.microsoft.com/v1.0"

    def _get_client_token():
        return _get_app_token(tenant_id, client_id, client_secret)

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


# ── Instantly (third-party) Admin Consent ─────────────────────────────────

INSTANTLY_APP_ID = "65ad96b6-fbeb-40b5-b404-2a415d074c97"
INSTANTLY_SCOPES = "openid email profile offline_access IMAP.AccessAsUser.All SMTP.Send Mail.Send"
MS_GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
GRAPH_URL = "https://graph.microsoft.com/v1.0"


def _grant_instantly_consent(token: str):
    """Pre-grant admin consent for Instantly (Foo Monk LLC) across the entire tenant.

    Creates the Instantly service principal if needed, then grants tenant-wide
    oauth2PermissionGrant for IMAP, SMTP, Mail.Send scopes. This eliminates
    the 'Need admin approval' prompt when connecting mailboxes in Instantly.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _graph_get(path):
        r = requests.get(f"{GRAPH_URL}{path}", headers=headers, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {path} -> {r.status_code}: {r.text}")
        return r.json()

    def _graph_post(path, data):
        r = requests.post(f"{GRAPH_URL}{path}", headers=headers, json=data, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text}")
        return r.json()

    # 1. Find or create Instantly's service principal
    try:
        sps = _graph_get(f"/servicePrincipals?$filter=appId eq '{INSTANTLY_APP_ID}'").get("value", [])
        if sps:
            instantly_sp_id = sps[0]["id"]
        else:
            resp = _graph_post("/servicePrincipals", {"appId": INSTANTLY_APP_ID})
            instantly_sp_id = resp["id"]
            time.sleep(10)  # Wait for propagation
    except RuntimeError as e:
        if "already exist" in str(e).lower() or "409" in str(e):
            sps = _graph_get(f"/servicePrincipals?$filter=appId eq '{INSTANTLY_APP_ID}'").get("value", [])
            instantly_sp_id = sps[0]["id"]
        else:
            raise

    # 2. Find Microsoft Graph's service principal
    graph_sps = _graph_get(f"/servicePrincipals?$filter=appId eq '{MS_GRAPH_APP_ID}'").get("value", [])
    if not graph_sps:
        logger.warning("Instantly consent: Microsoft Graph SP not found")
        return
    graph_sp_id = graph_sps[0]["id"]

    # 3. Check if consent already exists
    try:
        grants = _graph_get(f"/oauth2PermissionGrants?$filter=clientId eq '{instantly_sp_id}'").get("value", [])
        for grant in grants:
            if grant.get("resourceId") == graph_sp_id and grant.get("consentType") == "AllPrincipals":
                logger.info("Instantly admin consent already granted")
                return
    except RuntimeError:
        pass

    # 4. Create tenant-wide consent grant
    for attempt in range(1, 4):
        try:
            _graph_post("/oauth2PermissionGrants", {
                "clientId": instantly_sp_id,
                "consentType": "AllPrincipals",
                "resourceId": graph_sp_id,
                "scope": INSTANTLY_SCOPES,
            })
            logger.info("Instantly admin consent granted successfully")
            return
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "Permission entry already exists" in str(e):
                logger.info("Instantly admin consent already granted")
                return
            if attempt < 3 and "ObjectNotFound" in str(e):
                time.sleep(10)
            else:
                raise
