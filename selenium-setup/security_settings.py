"""Disable security defaults and MFA settings via Graph API.

Uses the token from az CLI (delegated admin access) — same approach as
tenant_setup_automation.py on the server.
"""

import json
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from config import GRAPH_URL


def _ts():
    return datetime.now().strftime("%H:%M:%S")

def info(msg):  print(f"[{_ts()}] INFO   {msg}")
def ok(msg):    print(f"[{_ts()}] OK     {msg}")
def warn(msg):  print(f"[{_ts()}] WARN   {msg}")


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
    """Disable Security Defaults via Graph API."""
    info("Disabling Security Defaults ...")
    try:
        _graph_patch(token, "policies/identitySecurityDefaultsEnforcementPolicy", {
            "isEnabled": False,
        })
        ok("Security Defaults DISABLED")
        return True
    except RuntimeError as e:
        warn(f"Security Defaults: {e}")
        return False


def disable_mfa_registration_campaign(token):
    """Disable MFA registration campaign."""
    info("Disabling MFA registration campaign ...")
    try:
        _graph_patch(token, "policies/authenticationMethodsPolicy", {
            "registrationCampaign": {"state": "disabled"},
        })
        ok("MFA registration campaign disabled")
        return True
    except RuntimeError as e:
        if "403" in str(e) or "AccessDenied" in str(e):
            warn("Endpoint restricted (may need higher privilege) — skipping")
            return False
        warn(f"MFA registration campaign: {e}")
        return False


def disable_system_preferred_mfa(token):
    """Disable system-preferred MFA."""
    info("Disabling system-preferred MFA ...")
    try:
        _graph_patch(token, "policies/authenticationMethodsPolicy", {
            "systemCredentialPreferences": {"state": "disabled"},
        }, api_version="beta")
        ok("System-preferred MFA disabled")
        return True
    except RuntimeError as e:
        if "403" in str(e) or "AccessDenied" in str(e):
            warn("Endpoint restricted — skipping")
            return False
        warn(f"System-preferred MFA: {e}")
        return False


def enable_smtp_auth_org(token, tenant_id=None, az_path=None):
    """Try to enable SMTP AUTH org-wide via multiple approaches."""
    info("Enabling SMTP AUTH (org-wide) ...")

    # Approach 1: Graph API beta
    try:
        _graph_patch(token, "admin/exchange/transportConfig", {
            "smtpClientAuthenticationDisabled": False,
        }, api_version="beta")
        ok("SMTP AUTH enabled via Graph API beta")
        return True
    except Exception as e:
        info(f"  Graph beta not available ({str(e)[:80]}), trying next ...")

    # Approach 2: Exchange REST API via az CLI token
    if az_path and tenant_id:
        try:
            from mfa_handler import get_exchange_token
            exchange_token = get_exchange_token(az_path)
            _exchange_invoke(exchange_token, tenant_id,
                "Set-TransportConfig",
                {"SmtpClientAuthenticationDisabled": False},
            )
            ok("SMTP AUTH enabled via Exchange REST API")
            return True
        except Exception as e:
            warn(f"Exchange REST API: {str(e)[:120]}")

    warn("Automated SMTP AUTH failed. Manual steps:")
    info("  1. Go to https://admin.exchange.microsoft.com")
    info("  2. Settings > Mail Flow")
    info("  3. UNCHECK 'Turn off SMTP AUTH protocol for the organization'")
    return False


def _exchange_invoke(exchange_token, tenant_id, cmdlet, parameters):
    """Call Exchange Online admin REST API."""
    url = f"https://outlook.office365.com/adminapi/beta/{tenant_id}/InvokeCommand"
    payload = {
        "CmdletInput": {
            "CmdletName": cmdlet,
            "Parameters": parameters,
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {exchange_token}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    with urlopen(req) as resp:
        body = resp.read().decode()
        return json.loads(body) if body else {"status": "success"}


def run_all_security_setup(token, tenant_id=None, az_path=None):
    """Run all security disabling steps."""
    disable_security_defaults(token)
    disable_mfa_registration_campaign(token)
    disable_system_preferred_mfa(token)
    enable_smtp_auth_org(token, tenant_id=tenant_id, az_path=az_path)
    ok("Security setup complete")
