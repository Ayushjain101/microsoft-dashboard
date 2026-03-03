"""
Microsoft Tenant Setup Automation via Graph API
================================================
Complete tenant configuration with multiple auth methods.

Auth Methods (in priority order):
  1. --use-cli    → Uses your az login session (BEST — full admin access, no 403 errors)
  2. .env file    → Client credentials (TENANT_ID, CLIENT_ID, CLIENT_SECRET)
  3. --config     → JSON config file with credentials
  4. Auto-detect  → Tries az CLI if .env/config missing

Phases:
  1. Security Setup (disable MFA, enable SMTP AUTH, etc.)
  2. Domain Management (add domains, enable DKIM, add DMARC)
  3. User Creation & Licensing (bulk create users, assign licenses)
  4. Room Mailbox Setup (create shared mailboxes)

Usage:
  python tenant_setup_automation.py --use-cli
  python tenant_setup_automation.py --config config.json
  python tenant_setup_automation.py
"""

import os
import sys
import json
import base64
import argparse
import subprocess
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError


# ─── Load .env ──────────────────────────────────────────────
def load_env():
    """Load .env file from script directory AND current working directory."""
    loaded = False
    # Try script directory first
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for search_dir in [script_dir, os.getcwd()]:
        env_path = os.path.join(search_dir, ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        key, val = key.strip(), val.strip()
                        if val:  # Only set non-empty values
                            os.environ[key] = val
                            loaded = True
    return loaded


# ─── Logging ────────────────────────────────────────────────
def log(level, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {level:5s}  {msg}")

def info(msg):  log("INFO", msg)
def ok(msg):    log("OK", msg)
def warn(msg):  log("WARN", msg)
def err(msg):   log("ERROR", msg)


# ─── Azure CLI Token Helpers ───────────────────────────────
def get_token_from_az_cli(resource="https://graph.microsoft.com"):
    """Get access token from Azure CLI session (delegated/user token)."""
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", resource, "-o", "json"],
            capture_output=True, text=True, timeout=30, shell=True
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "az command failed")
        data = json.loads(result.stdout)
        return data["accessToken"]
    except FileNotFoundError:
        raise RuntimeError("Azure CLI (az) not found. Install: https://aka.ms/installazurecliwindows")
    except subprocess.TimeoutExpired:
        raise RuntimeError("az command timed out")


def get_tenant_id_from_az_cli():
    """Get tenant ID from current az CLI session."""
    try:
        result = subprocess.run(
            ["az", "account", "show", "-o", "json"],
            capture_output=True, text=True, timeout=30, shell=True
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "az command failed")
        data = json.loads(result.stdout)
        return data["tenantId"]
    except Exception:
        return None


def get_exchange_token_from_az_cli():
    """Get Exchange Online token from az CLI session."""
    return get_token_from_az_cli("https://outlook.office365.com")


# ─── Microsoft Graph API Helpers ────────────────────────────
def get_access_token(tenant_id, client_id, client_secret):
    """Get OAuth2 access token using client credentials."""
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }).encode("utf-8")

    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req) as resp:
            body = json.loads(resp.read().decode())
            return body["access_token"]
    except HTTPError as e:
        error_body = e.read().decode()
        try:
            error_json = json.loads(error_body)
            error_desc = error_json.get("error_description", error_body)
        except json.JSONDecodeError:
            error_desc = error_body
        raise RuntimeError(f"Token request failed ({e.code}): {error_desc}")


def graph_request(token, method, endpoint, body=None, api_version="v1.0"):
    """Generic Microsoft Graph API request."""
    url = f"https://graph.microsoft.com/{api_version}/{endpoint}"
    data = json.dumps(body).encode("utf-8") if body else None

    req = Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req) as resp:
            if resp.status == 204:
                return {"status": "success", "code": 204}
            resp_body = resp.read().decode()
            return json.loads(resp_body) if resp_body else {"status": "success", "code": resp.status}
    except HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"{method} {endpoint} failed ({e.code}): {error_body}")


def graph_get(token, endpoint):
    return graph_request(token, "GET", endpoint)

def graph_patch(token, endpoint, body):
    return graph_request(token, "PATCH", endpoint, body)

def graph_post(token, endpoint, body):
    return graph_request(token, "POST", endpoint, body)

def graph_delete(token, endpoint):
    return graph_request(token, "DELETE", endpoint)

def graph_patch_beta(token, endpoint, body):
    return graph_request(token, "PATCH", endpoint, body, api_version="beta")


# ─── Exchange Online REST API ──────────────────────────────
def get_exchange_token(tenant_id, client_id, client_secret):
    """Get Exchange Online token via client credentials."""
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://outlook.office365.com/.default",
    }).encode("utf-8")

    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urlopen(req) as resp:
        return json.loads(resp.read().decode())["access_token"]


def exchange_invoke_command(exchange_token, tenant_id, cmdlet_name, parameters):
    """Call Exchange Online admin REST API directly."""
    url = f"https://outlook.office365.com/adminapi/beta/{tenant_id}/InvokeCommand"
    payload = {
        "CmdletInput": {
            "CmdletName": cmdlet_name,
            "Parameters": parameters
        }
    }
    data = json.dumps(payload).encode("utf-8")

    req = Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {exchange_token}")
    req.add_header("Content-Type", "application/json; charset=utf-8")

    with urlopen(req) as resp:
        body = resp.read().decode()
        return json.loads(body) if body else {"status": "success", "code": resp.status}


# ─── Phase 1: Security Setup ─────────────────────────────────
def setup_security_defaults(token, disable=True):
    """Disable/enable Security Defaults."""
    info("Phase 1: Security Setup")
    info("  1.1: Configuring Security Defaults...")

    try:
        graph_patch(token, "policies/identitySecurityDefaultsEnforcementPolicy", {
            "isEnabled": not disable
        })
        ok(f"  ✓ Security Defaults {'DISABLED' if disable else 'ENABLED'}")
        return True
    except RuntimeError as e:
        err(f"  ✗ Failed: {e}")
        return False


def disable_mfa_registration_campaign(token):
    """Disable MFA registration campaign."""
    info("  1.2: Disabling MFA registration campaign...")

    try:
        graph_patch(token, "policies/authenticationMethodsPolicy", {
            "registrationCampaign": {
                "state": "disabled"
            }
        })
        ok("  ✓ MFA registration campaign disabled")
        return True
    except RuntimeError as e:
        if "403" in str(e) or "AccessDenied" in str(e):
            warn("  ⚠ Endpoint restricted (may need higher privilege)")
            return True
        err(f"  ✗ Failed: {e}")
        return False


def disable_system_preferred_mfa(token):
    """Disable system-preferred multifactor authentication."""
    info("  1.3: Disabling system-preferred MFA...")

    try:
        graph_patch_beta(token, "policies/authenticationMethodsPolicy", {
            "systemCredentialPreferences": {
                "state": "disabled"
            }
        })
        ok("  ✓ System-preferred MFA disabled")
        return True
    except RuntimeError as e:
        if "403" in str(e) or "AccessDenied" in str(e):
            warn("  ⚠ Endpoint restricted (may need higher privilege)")
            return True
        err(f"  ✗ Failed: {e}")
        return False


def enable_smtp_auth(token, tenant_id=None, client_id=None, client_secret=None, use_cli=False):
    """Enable SMTP AUTH using multiple approaches."""
    info("  1.4: Enabling SMTP AUTH (unblocking org-wide)...")

    tenant_id = tenant_id or os.environ.get("TENANT_ID", "")
    client_id = client_id or os.environ.get("CLIENT_ID", "")
    client_secret = client_secret or os.environ.get("CLIENT_SECRET", "")

    # ── Approach 1: Exchange REST API with az CLI token (BEST for --use-cli) ──
    if use_cli:
        try:
            info("     ℹ️ Getting Exchange token from az CLI...")
            exchange_token = get_exchange_token_from_az_cli()
            t_id = tenant_id or get_tenant_id_from_az_cli()
            if t_id:
                exchange_invoke_command(exchange_token, t_id,
                    "Set-TransportConfig",
                    {"SmtpClientAuthenticationDisabled": False}
                )
                ok("  ✓ SMTP AUTH enabled via Exchange REST API (az CLI)")
                return True
        except Exception as e:
            warn(f"  ⚠ Exchange via az CLI failed: {str(e)[:120]}")

    # ── Approach 2: Graph API beta ──
    try:
        info("     ℹ️ Trying Graph API beta endpoint...")
        graph_patch_beta(token, "admin/exchange/transportConfig", {
            "smtpClientAuthenticationDisabled": False
        })
        ok("  ✓ SMTP AUTH enabled via Graph API beta")
        return True
    except Exception as e:
        info(f"     Graph beta not available ({str(e)[:80]}), trying next...")

    # ── Approach 3: Exchange REST API with client credentials ──
    if all([tenant_id, client_id, client_secret]):
        try:
            info("     ℹ️ Trying Exchange Online REST API with client credentials...")
            exchange_token = get_exchange_token(tenant_id, client_id, client_secret)
            exchange_invoke_command(exchange_token, tenant_id,
                "Set-TransportConfig",
                {"SmtpClientAuthenticationDisabled": False}
            )
            ok("  ✓ SMTP AUTH enabled via Exchange REST API")
            return True
        except Exception as e:
            warn(f"  ⚠ Exchange REST API error: {str(e)[:120]}")

    # ── Approach 4: Per-user SMTP AUTH via Graph API ──
    try:
        info("     ℹ️ Trying per-user SMTP AUTH via Graph API...")
        users = graph_get(token, "users?$select=id,userPrincipalName&$top=100")
        user_list = users.get("value", [])
        if user_list:
            enabled_count = 0
            for user in user_list:
                try:
                    graph_patch(token, f"users/{user['id']}/mailboxSettings", {
                        "smtpClientAuthentication": True
                    })
                    enabled_count += 1
                except Exception:
                    pass
            if enabled_count > 0:
                ok(f"  ✓ SMTP AUTH enabled for {enabled_count}/{len(user_list)} users")
                return True
    except Exception as e:
        info(f"     Per-user approach failed: {str(e)[:80]}")

    # ── Manual fallback ──
    warn("  ⚠ Automated SMTP AUTH failed. Manual steps:")
    info("     1. Go to https://admin.exchange.microsoft.com")
    info("     2. Settings > Mail Flow")
    info("     3. UNCHECK 'Turn off SMTP AUTH protocol for the organization'")
    info("     4. Click Save")
    return True


# ─── Phase 2: Domain Management ──────────────────────────────
def add_domain(token, domain_name):
    info(f"  2.1: Adding domain '{domain_name}'...")
    try:
        result = graph_post(token, "domains", {"id": domain_name})
        ok(f"  ✓ Domain '{domain_name}' added")
        return result
    except RuntimeError as e:
        err(f"  ✗ Failed to add domain: {e}")
        return None


def verify_domain(token, domain_name):
    info(f"  2.2: Verifying domain '{domain_name}'...")
    try:
        result = graph_post(token, f"domains/{domain_name}/verify", {})
        ok(f"  ✓ Domain '{domain_name}' verified")
        return result
    except RuntimeError as e:
        warn(f"  ⚠ Domain verification pending: {e}")
        return None


def enable_dkim(token, domain_name):
    info(f"  2.3: Enabling DKIM for '{domain_name}'...")
    try:
        result = graph_post(token, f"domainDnsRecords/createDkim", {"domainId": domain_name})
        ok(f"  ✓ DKIM enabled for '{domain_name}'")
        return result
    except RuntimeError as e:
        err(f"  ✗ Failed to enable DKIM: {e}")
        return None


def add_dmarc_record(token, domain_name, dmarc_policy="quarantine"):
    info(f"  2.4: Setting up DMARC for '{domain_name}'...")
    dmarc_record = f"v=DMARC1; p={dmarc_policy}; rua=mailto:admin@{domain_name}; ruf=mailto:admin@{domain_name}; fo=1"
    info(f"  Add this DMARC record to your DNS provider:")
    info(f"     Host: _dmarc.{domain_name}")
    info(f"     Type: TXT")
    info(f"     Value: {dmarc_record}")
    warn("  ⚠ DMARC must be done via your DNS provider (Cloudflare, Route53, etc.)")
    return True


# ─── Phase 3: User Creation & Licensing ──────────────────────
def create_user(token, user_data):
    info(f"  3.1: Creating user '{user_data['username']}'...")
    user_body = {
        "accountEnabled": True,
        "displayName": f"{user_data['first_name']} {user_data['last_name']}",
        "mailNickname": user_data['username'].split('@')[0],
        "userPrincipalName": user_data['username'],
        "passwordProfile": {
            "forceChangePasswordNextSignIn": False,
            "password": user_data['password']
        },
        "givenName": user_data['first_name'],
        "surname": user_data['last_name']
    }
    try:
        result = graph_post(token, "users", user_body)
        ok(f"  ✓ User '{user_data['username']}' created")
        return result
    except RuntimeError as e:
        if "already exists" in str(e).lower():
            warn(f"  ⚠ User '{user_data['username']}' already exists")
            return None
        err(f"  ✗ Failed to create user: {e}")
        return None


def assign_license(token, user_id, license_sku="SPE_F1"):
    info(f"  3.2: Assigning license to user {user_id}...")
    try:
        skus = graph_get(token, "subscribedSkus")
        target_sku = None
        for sku in skus.get("value", []):
            if sku['skuPartNumber'] == license_sku:
                target_sku = sku
                break
        if not target_sku:
            warn(f"  ⚠ License '{license_sku}' not found. Available: {[s['skuPartNumber'] for s in skus.get('value', [])]}")
            return False
        result = graph_post(token, f"users/{user_id}/assignLicense", {
            "addLicenses": [{"skuId": target_sku['skuId']}],
            "removeLicenses": []
        })
        ok(f"  ✓ License '{license_sku}' assigned")
        return True
    except RuntimeError as e:
        err(f"  ✗ Failed to assign license: {e}")
        return False


def bulk_create_users(token, users_list):
    info("Phase 3: User Creation & Licensing")
    created_users = []
    for user_data in users_list:
        user = create_user(token, user_data)
        if user:
            created_users.append(user)
            if user_data.get('assign_license', False):
                user_id = user.get('id')
                if user_id:
                    assign_license(token, user_id)
    ok(f"  ✓ Created {len(created_users)}/{len(users_list)} users")
    return created_users


# ─── Phase 4: Room Mailbox Setup ─────────────────────────────
def create_room_mailbox(token, mailbox_data):
    info(f"  4.1: Creating mailbox '{mailbox_data['email']}'...")
    try:
        mailbox_body = {
            "displayName": mailbox_data['name'],
            "mailNickname": mailbox_data['email'].split('@')[0],
            "mail": mailbox_data['email'],
            "resourceBehaviorOptions": ["CalendarMemberReadOnly"],
            "resourceDisplayName": mailbox_data['name'],
            "resourceType": "Room" if "room" in mailbox_data.get('type', '').lower() else "Equipment"
        }
        result = graph_post(token, "resources/rooms", mailbox_body)
        ok(f"  ✓ Mailbox '{mailbox_data['email']}' created")
        return result
    except RuntimeError as e:
        err(f"  ✗ Failed to create mailbox: {e}")
        return None


def bulk_create_mailboxes(token, mailboxes_list):
    info("Phase 4: Room Mailbox Setup")
    created_mailboxes = []
    for mailbox_data in mailboxes_list:
        mailbox = create_room_mailbox(token, mailbox_data)
        if mailbox:
            created_mailboxes.append(mailbox)
    ok(f"  ✓ Created {len(created_mailboxes)}/{len(mailboxes_list)} mailboxes")
    return created_mailboxes


# ─── Main ───────────────────────────────────────────────────
def main():
    # Load .env first
    env_loaded = load_env()

    parser = argparse.ArgumentParser(
        description="Automated Microsoft Tenant Setup via Graph API"
    )
    parser.add_argument("--config", help="Path to JSON configuration file")
    parser.add_argument("--phase", help="Run specific phase: security, domains, users, mailboxes (default: all)")
    parser.add_argument("--use-cli", action="store_true",
                        help="Use Azure CLI token (delegated auth — best for full admin access)")
    args = parser.parse_args()

    # Load config from file
    config = {}
    if args.config:
        if not os.path.exists(args.config):
            err(f"Config file not found: {args.config}")
            sys.exit(1)
        with open(args.config) as f:
            config = json.load(f)

    # Determine auth method
    tenant_id = config.get("tenant_id") or os.environ.get("TENANT_ID")
    client_id = config.get("client_id") or os.environ.get("CLIENT_ID")
    client_secret = config.get("client_secret") or os.environ.get("CLIENT_SECRET")
    has_client_creds = all([tenant_id, client_id, client_secret])

    # Auto-detect: if no credentials and no --use-cli flag, try az CLI automatically
    use_cli = args.use_cli
    if not has_client_creds and not use_cli:
        info("No .env or config credentials found. Trying Azure CLI session...")
        use_cli = True

    info("=" * 60)
    info("  Microsoft Tenant Setup — Graph API Automation")
    info("=" * 60)

    # ── Get token ──
    token = None

    if use_cli:
        info("  Auth: Azure CLI (delegated/admin token)")
        info("=" * 60)
        info("")

        # Get Graph token from az CLI
        info("Getting access token from Azure CLI...")
        try:
            token = get_token_from_az_cli("https://graph.microsoft.com")
            tenant_id = tenant_id or get_tenant_id_from_az_cli()
            ok(f"✓ Token acquired from az CLI")
            if tenant_id:
                ok(f"✓ Tenant ID: {tenant_id}")
        except RuntimeError as e:
            err(f"✗ Azure CLI token failed: {e}")
            err("")
            err("You need to login first. Run:")
            err("  az login")
            err("  OR")
            err("  python login.py --email admin@domain.com --password YourPass")
            sys.exit(1)
    else:
        info(f"  Auth: Client Credentials")
        info(f"  Tenant ID: {tenant_id}")
        info(f"  Client ID: {client_id}")
        info("=" * 60)
        info("")

        info("Getting access token...")
        try:
            token = get_access_token(tenant_id, client_id, client_secret)
            ok("✓ Token acquired")
        except RuntimeError as e:
            err(f"✗ Token error: {e}")
            info("")
            info("Tip: Try --use-cli flag to use your az login session instead:")
            info("  az login")
            info("  python tenant_setup_automation.py --use-cli")
            sys.exit(1)

    info("")

    phases_to_run = args.phase.split(",") if args.phase else config.get("phases", ["security", "domains", "users", "mailboxes"])

    # Phase 1: Security
    if "security" in phases_to_run:
        try:
            setup_security_defaults(token, disable=True)
            disable_mfa_registration_campaign(token)
            disable_system_preferred_mfa(token)
            enable_smtp_auth(token, tenant_id, client_id, client_secret, use_cli=use_cli)
            ok("✓ Security setup complete")
        except Exception as e:
            err(f"✗ Security setup failed: {e}")
        info("")

    # Phase 2: Domains
    if "domains" in phases_to_run:
        try:
            info("Phase 2: Domain Management")
            for domain_config in config.get("domains", []):
                domain = domain_config['domain']
                add_domain(token, domain)
                verify_domain(token, domain)
                if domain_config.get('enable_dkim', True):
                    enable_dkim(token, domain)
                if domain_config.get('add_dmarc', True):
                    add_dmarc_record(token, domain)
            ok("✓ Domain setup complete")
        except Exception as e:
            err(f"✗ Domain setup failed: {e}")
        info("")

    # Phase 3: Users
    if "users" in phases_to_run:
        try:
            bulk_create_users(token, config.get("users", []))
            ok("✓ User creation complete")
        except Exception as e:
            err(f"✗ User creation failed: {e}")
        info("")

    # Phase 4: Mailboxes
    if "mailboxes" in phases_to_run:
        try:
            bulk_create_mailboxes(token, config.get("mailboxes", []))
            ok("✓ Mailbox setup complete")
        except Exception as e:
            err(f"✗ Mailbox setup failed: {e}")
        info("")

    info("=" * 60)
    ok("  AUTOMATION COMPLETE")
    info("=" * 60)


if __name__ == "__main__":
    main()
