"""Disable security defaults and MFA settings via Graph API.

Uses the token from az CLI (delegated admin access).
"""

import json
import logging
from urllib.request import Request, urlopen
from urllib.error import HTTPError

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.microsoft.com/v1.0"


def _graph_patch(token, endpoint, body, api_version="v1.0"):
    url = f"https://graph.microsoft.com/{api_version}/{endpoint}"
    data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req) as resp:
            if resp.status == 204:
                return {"status": "success"}
            body_text = resp.read().decode()
            return json.loads(body_text) if body_text else {"status": "success"}
    except HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"PATCH {endpoint} failed ({e.code}): {error_body[:300]}")


def disable_security_defaults(token):
    logger.info("Disabling Security Defaults ...")
    try:
        _graph_patch(token, "policies/identitySecurityDefaultsEnforcementPolicy", {"isEnabled": False})
        logger.info("Security Defaults DISABLED")
        return True
    except RuntimeError as e:
        logger.warning(f"Security Defaults: {e}")
        return False


def disable_mfa_registration_campaign(token):
    logger.info("Disabling MFA registration campaign ...")
    try:
        _graph_patch(token, "policies/authenticationMethodsPolicy", {
            "registrationCampaign": {"state": "disabled"},
        })
        logger.info("MFA registration campaign disabled")
        return True
    except RuntimeError as e:
        if "403" in str(e) or "AccessDenied" in str(e):
            logger.warning("Endpoint restricted — skipping")
            return False
        logger.warning(f"MFA registration campaign: {e}")
        return False


def disable_system_preferred_mfa(token):
    logger.info("Disabling system-preferred MFA ...")
    try:
        _graph_patch(token, "policies/authenticationMethodsPolicy", {
            "systemCredentialPreferences": {"state": "disabled"},
        }, api_version="beta")
        logger.info("System-preferred MFA disabled")
        return True
    except RuntimeError as e:
        if "403" in str(e) or "AccessDenied" in str(e):
            logger.warning("Endpoint restricted — skipping")
            return False
        logger.warning(f"System-preferred MFA: {e}")
        return False


def enable_smtp_auth_org(token, tenant_id=None, az_path=None):
    logger.info("Enabling SMTP AUTH (org-wide) ...")
    try:
        _graph_patch(token, "admin/exchange/transportConfig", {
            "smtpClientAuthenticationDisabled": False,
        }, api_version="beta")
        logger.info("SMTP AUTH enabled via Graph API beta")
        return True
    except Exception as e:
        logger.info(f"Graph beta not available ({str(e)[:80]}), trying next ...")

    if az_path and tenant_id:
        try:
            from app.selenium_worker.mfa_handler import get_exchange_token
            exchange_token = get_exchange_token(az_path)
            _exchange_invoke(exchange_token, tenant_id, "Set-TransportConfig",
                             {"SmtpClientAuthenticationDisabled": False})
            logger.info("SMTP AUTH enabled via Exchange REST API")
            return True
        except Exception as e:
            logger.warning(f"Exchange REST API: {str(e)[:120]}")

    logger.warning("Automated SMTP AUTH failed")
    return False


def _exchange_invoke(exchange_token, tenant_id, cmdlet, parameters):
    url = f"https://outlook.office365.com/adminapi/beta/{tenant_id}/InvokeCommand"
    payload = {"CmdletInput": {"CmdletName": cmdlet, "Parameters": parameters}}
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {exchange_token}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    with urlopen(req) as resp:
        body = resp.read().decode()
        return json.loads(body) if body else {"status": "success"}


def run_all_security_setup(token, tenant_id=None, az_path=None):
    disable_security_defaults(token)
    disable_mfa_registration_campaign(token)
    disable_system_preferred_mfa(token)
    enable_smtp_auth_org(token, tenant_id=tenant_id, az_path=az_path)
    logger.info("Security setup complete")
