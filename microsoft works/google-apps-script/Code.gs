/**
 * Azure App Registration Automation — Google Apps Script
 *
 * Sheet layout (Row 1 = headers, Row 2+ = data):
 *   A: Admin Email | B: Password | C: New Password | D: Tenant ID | E: Client ID | F: Client Secret | G: Status
 */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Automation")
    .addItem("START Registration", "setStart")
    .addToUi();
}

function setStart() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  if (!sheet.getRange("A1").getValue()) {
    sheet.getRange("A1").setValue("Admin Email");
    sheet.getRange("B1").setValue("Password");
    sheet.getRange("C1").setValue("New Password");
    sheet.getRange("D1").setValue("Tenant ID");
    sheet.getRange("E1").setValue("Client ID");
    sheet.getRange("F1").setValue("Client Secret");
    sheet.getRange("G1").setValue("Status");
  }
  var lastRow = sheet.getLastRow();
  var startSet = false;
  for (var i = 2; i <= lastRow; i++) {
    var email = sheet.getRange("A" + i).getValue();
    var password = sheet.getRange("B" + i).getValue();
    var tenantId = sheet.getRange("D" + i).getValue();
    if (email && password && !tenantId) {
      if (!startSet) {
        sheet.getRange("G" + i).setValue("START");
        startSet = true;
      } else {
        sheet.getRange("G" + i).setValue("QUEUED");
      }
    }
  }
  if (startSet) {
    SpreadsheetApp.getUi().alert("Rows marked for processing. Run the automation now.");
  } else {
    SpreadsheetApp.getUi().alert("No pending rows found. Add email + password first.");
  }
}

function doGet(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var lastRow = sheet.getLastRow();

  var pending = [];
  var hasStart = false;
  for (var i = 2; i <= lastRow; i++) {
    var email = sheet.getRange("A" + i).getValue();
    var password = sheet.getRange("B" + i).getValue();
    var newPassword = sheet.getRange("C" + i).getValue();
    var tenantId = sheet.getRange("D" + i).getValue();
    var rowStatus = sheet.getRange("G" + i).getValue();

    if (rowStatus === "START" || rowStatus === "QUEUED") {
      hasStart = true;
    }

    if (email && password && !tenantId) {
      pending.push({
        row: i,
        email: String(email),
        password: String(password),
        newPassword: newPassword ? String(newPassword) : ""
      });
    }
  }

  var result = {
    status: hasStart ? "START" : "IDLE",
    pending: pending,
    totalRows: lastRow - 1
  };

  return ContentService
    .createTextOutput(JSON.stringify(result))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();

  try {
    var data = JSON.parse(e.postData.contents);

    // Update per-row status in column G
    if (data.action === "rowStatus" && data.row) {
      sheet.getRange("G" + data.row).setValue(data.status || "");
      return ContentService
        .createTextOutput(JSON.stringify({ result: "ok", row: data.row }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Write credentials to a specific row (columns D, E, F)
    if (data.action === "credentials" && data.row) {
      var row = data.row;
      sheet.getRange("D" + row).setValue(data.tenantId || "");
      sheet.getRange("E" + row).setValue(data.clientId || "");
      sheet.getRange("F" + row).setValue(data.clientSecret || "");
      sheet.getRange("G" + row).setValue("COMPLETE");
      return ContentService
        .createTextOutput(JSON.stringify({ result: "ok", row: row }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Write error for a specific row
    if (data.action === "error" && data.row) {
      sheet.getRange("D" + data.row).setValue("ERROR: " + (data.message || "unknown"));
      sheet.getRange("G" + data.row).setValue("FAILED");
      return ContentService
        .createTextOutput(JSON.stringify({ result: "ok", row: data.row }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Update password in column B after password change
    if (data.action === "updatePassword" && data.row) {
      sheet.getRange("B" + data.row).setValue(data.password || "");
      return ContentService
        .createTextOutput(JSON.stringify({ result: "ok", row: data.row }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    return ContentService
      .createTextOutput(JSON.stringify({ result: "unknown action" }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ result: "error", message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
,,, """
Microsoft Tenant Setup Automation via Graph API
================================================
Complete tenant configuration using client credentials (tenant ID, client ID, client secret).

Phases:
  1. Security Setup (disable MFA, enable SMTP AUTH, etc.)
  2. Domain Management (add domains, enable DKIM, add DMARC)
  3. User Creation & Licensing (bulk create users, assign licenses)
  4. Room Mailbox Setup (create shared mailboxes)

Usage:
  python tenant_setup_automation.py --config config.json

Config JSON format:
{
  "tenant_id": "...",
  "client_id": "...",
  "client_secret": "...",
  "admin_email": "admin@yourdomain.com",
  "phases": ["security", "domains", "users", "mailboxes"],
  "domains": [
    {
      "domain": "example.com",
      "enable_dkim": true,
      "add_dmarc": true
    }
  ],
  "users": [
    {
      "first_name": "John",
      "last_name": "Doe",
      "username": "john@example.com",
      "password": "SecurePass123!",
      "domain": "example.com",
      "assign_license": true
    }
  ],
  "mailboxes": [
    {
      "name": "Sales Team",
      "email": "sales@example.com",
      "type": "SharedMailbox"
    }
  ]
}

Required API Permissions:
  - Policy.ReadWrite.ConditionalAccess (write security defaults)
  - Domain.ReadWrite.All (manage domains)
  - User.ReadWrite.All (create/manage users)
  - Organization.ReadWrite.All (org settings)
  - Mail.ReadWrite (exchange/mailbox settings)
  - Directory.ReadWrite.All (general directory ops)
"""

import os
import sys
import json
import base64
import argparse
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError


# ─── Load .env ──────────────────────────────────────────────
def load_env():
    """Load .env file from the same directory as this script."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


# ─── Logging ────────────────────────────────────────────────
def log(level, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {level:5s}  {msg}")

def info(msg):  log("INFO", msg)
def ok(msg):    log("OK", msg)
def warn(msg):  log("WARN", msg)
def err(msg):   log("ERROR", msg)


# ─── JWT Helpers ────────────────────────────────────────────
def _b64url_decode(s: str) -> bytes:
    s = s.strip()
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("utf-8"))

def decode_jwt_noverify(token: str):
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}, {}
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        return header, payload
    except Exception:
        return {}, {}


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


def graph_get(token, endpoint):
    """GET request to Microsoft Graph API."""
    url = f"https://graph.microsoft.com/v1.0/{endpoint}"
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"GET {endpoint} failed ({e.code}): {error_body}")


def graph_patch(token, endpoint, body):
    """PATCH request to Microsoft Graph API."""
    url = f"https://graph.microsoft.com/v1.0/{endpoint}"
    data = json.dumps(body).encode("utf-8")

    req = Request(url, data=data, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req) as resp:
            if resp.status == 204:
                return {"status": "success", "code": 204}
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"PATCH {endpoint} failed ({e.code}): {error_body}")


def graph_post(token, endpoint, body):
    """POST request to Microsoft Graph API."""
    url = f"https://graph.microsoft.com/v1.0/{endpoint}"
    data = json.dumps(body).encode("utf-8")

    req = Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req) as resp:
            if resp.status in [200, 201, 204]:
                if resp.status == 204:
                    return {"status": "success", "code": 204}
                body = resp.read().decode()
                return json.loads(body) if body else {"status": "success", "code": resp.status}
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"POST {endpoint} failed ({e.code}): {error_body}")


def graph_delete(token, endpoint):
    """DELETE request to Microsoft Graph API."""
    url = f"https://graph.microsoft.com/v1.0/{endpoint}"
    req = Request(url, method="DELETE")
    req.add_header("Authorization", f"Bearer {token}")

    try:
        with urlopen(req) as resp:
            if resp.status == 204:
                return {"status": "success", "code": 204}
            body = resp.read().decode()
            return json.loads(body) if body else {"status": "success", "code": resp.status}
    except HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"DELETE {endpoint} failed ({e.code}): {error_body}")


# ─── Phase 1: Security Setup ─────────────────────────────────
def setup_security_defaults(token, disable=True):
    """Disable/enable Security Defaults."""
    info("Phase 1: Security Setup")
    info("  1.1: Configuring Security Defaults...")
    
    try:
        result = graph_patch(token, "policies/identitySecurityDefaultsEnforcementPolicy", {
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
    info("     ℹ️ Attempting via authenticationMethodsPolicy endpoint...")
    
    try:
        result = graph_patch(token, "policies/authenticationMethodsPolicy", {
            "registrationCampaign": {
                "enforceRegistrationAfterAllowListExpires": False,
                "includeTarget": {
                    "targetType": "group",
                    "id": "00000000-0000-0000-0000-000000000000"
                }
            }
        })
        ok("  ✓ MFA registration campaign disabled")
        return True
    except RuntimeError as e:
        if "403" in str(e) or "AccessDenied" in str(e):
            warn(f"  ⚠ Endpoint restricted (403)")
            info("     This may be restricted by tenant conditional access policies")
            info("     Manual: entra.microsoft.com > Identity > Protection > Authentication methods > Registration campaign > State = Disabled")
            warn("     Continuing with other automation steps...")
            return True
        else:
            err(f"  ✗ Failed: {e}")
            return False


def disable_system_preferred_mfa(token):
    """Disable system-preferred multifactor authentication."""
    info("  1.3: Disabling system-preferred MFA...")
    info("     ℹ️ Attempting via authenticationMethodsPolicy endpoint...")
    
    try:
        result = graph_patch(token, "policies/authenticationMethodsPolicy", {
            "systemPreferredAuthenticationMethods": []
        })
        ok("  ✓ System-preferred MFA disabled")
        return True
    except RuntimeError as e:
        if "403" in str(e) or "AccessDenied" in str(e):
            warn(f"  ⚠ Endpoint restricted (403)")
            info("     This may be restricted by tenant conditional access policies")
            info("     Manual: entra.microsoft.com > Identity > Protection > Authentication methods > Settings > System-preferred MFA > State = Disabled")
            warn("     Continuing with other automation steps...")
            return True
        else:
            err(f"  ✗ Failed: {e}")
            return False


def get_exchange_token(tenant_id, client_id, client_secret):
    """Get OAuth2 access token for Exchange Online REST API."""
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
        body = json.loads(resp.read().decode())
        return body["access_token"]


def exchange_invoke_command(exchange_token, tenant_id, cmdlet_name, parameters):
    """Call Exchange Online REST API directly (same API that PowerShell uses)."""
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


def graph_patch_beta(token, endpoint, body):
    """PATCH request to Microsoft Graph BETA API."""
    url = f"https://graph.microsoft.com/beta/{endpoint}"
    data = json.dumps(body).encode("utf-8")

    req = Request(url, data=data, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    with urlopen(req) as resp:
        if resp.status == 204:
            return {"status": "success", "code": 204}
        body_text = resp.read().decode()
        return json.loads(body_text) if body_text else {"status": "success", "code": resp.status}


def enable_smtp_auth(token, tenant_id=None, client_id=None, client_secret=None):
    """Enable SMTP AUTH using multiple approaches (Graph API, Exchange REST API)."""
    info("  1.4: Enabling SMTP AUTH (unblocking org-wide)...")

    # Get credentials from params or environment
    tenant_id = tenant_id or os.environ.get("TENANT_ID", "")
    client_id = client_id or os.environ.get("CLIENT_ID", "")
    client_secret = client_secret or os.environ.get("CLIENT_SECRET", "")

    # ── Approach 1: Graph API beta endpoint ──
    try:
        info("     ℹ️ Trying Graph API beta endpoint...")
        graph_patch_beta(token, "admin/exchange/transportConfig", {
            "smtpClientAuthenticationDisabled": False
        })
        ok("  ✓ SMTP AUTH enabled via Graph API beta")
        return True
    except Exception as e:
        info(f"     Graph beta not available ({str(e)[:80]}), trying next...")

    # ── Approach 2: Exchange Online REST API directly (no PowerShell needed) ──
    if all([tenant_id, client_id, client_secret]):
        try:
            info("     ℹ️ Trying Exchange Online REST API...")
            exchange_token = get_exchange_token(tenant_id, client_id, client_secret)
            exchange_invoke_command(exchange_token, tenant_id,
                "Set-TransportConfig",
                {"SmtpClientAuthenticationDisabled": False}
            )
            ok("  ✓ SMTP AUTH enabled via Exchange REST API")
            return True
        except HTTPError as e:
            error_body = e.read().decode() if hasattr(e, 'read') else str(e)
            if e.code == 401 or "Unauthorized" in str(error_body):
                warn("  ⚠ Exchange REST API: Unauthorized")
                info("     Your app needs 'Exchange.ManageAsApp' permission:")
                info("     → Azure Portal > App registrations > Your app > API permissions")
                info("     → Add permission > APIs my organization uses > Office 365 Exchange Online")
                info("     → Application permissions > Exchange.ManageAsApp > Add")
                info("     → Grant admin consent")
                info("     Also assign Exchange Administrator role to the app:")
                info("     → Azure Portal > Roles and administrators > Exchange Administrator")
                info("     → Add assignment > Select your app's service principal")
            elif e.code == 403:
                warn("  ⚠ Exchange REST API: Forbidden (missing Exchange Administrator role)")
                info("     → Azure Portal > Roles and administrators > Exchange Administrator")
                info("     → Add assignment > Select your app's service principal")
            else:
                warn(f"  ⚠ Exchange REST API error ({e.code}): {str(error_body)[:150]}")
        except Exception as e:
            warn(f"  ⚠ Exchange REST API error: {str(e)[:150]}")
    else:
        warn("  ⚠ Missing credentials for Exchange REST API")

    # ── Approach 3: Per-user SMTP AUTH via Graph API ──
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
            else:
                info("     Per-user SMTP setting not available via Graph API")
        else:
            info("     No users found for per-user SMTP AUTH")
    except Exception as e:
        info(f"     Per-user approach failed: {str(e)[:80]}")

    # ── All automated approaches failed — show manual steps ──
    warn("  ⚠ Automated SMTP AUTH failed. Follow these manual steps:")
    info("     ──────────────────────────────────────────────────")
    info("     OPTION A: Exchange Admin Center (easiest)")
    info("       1. Go to https://admin.exchange.microsoft.com")
    info("       2. Settings > Mail Flow")
    info("       3. UNCHECK 'Turn off SMTP AUTH protocol for the organization'")
    info("       4. Click Save")
    info("     ──────────────────────────────────────────────────")
    info("     OPTION B: Fix app permissions (for full automation)")
    info("       1. Azure Portal > App registrations > Your app > API permissions")
    info("       2. Add: Office 365 Exchange Online > Exchange.ManageAsApp")
    info("       3. Grant admin consent")
    info("       4. Assign Exchange Administrator role to the app")
    info("       5. Re-run this script")
    info("     ──────────────────────────────────────────────────")
    return True


# ─── Phase 2: Domain Management ──────────────────────────────
def add_domain(token, domain_name):
    """Add a domain to the tenant."""
    info(f"  2.1: Adding domain '{domain_name}'...")
    
    try:
        result = graph_post(token, "domains", {
            "id": domain_name
        })
        ok(f"  ✓ Domain '{domain_name}' added")
        return result
    except RuntimeError as e:
        err(f"  ✗ Failed to add domain: {e}")
        return None


def verify_domain(token, domain_name):
    """Verify a domain (requires DNS records to be set)."""
    info(f"  2.2: Verifying domain '{domain_name}'...")
    
    try:
        result = graph_post(token, f"domains/{domain_name}/verify", {})
        ok(f"  ✓ Domain '{domain_name}' verified")
        return result
    except RuntimeError as e:
        warn(f"  ⚠ Domain verification pending: {e}")
        warn(f"     Make sure DNS records are set in your provider (Cloudflare, etc.)")
        return None


def enable_dkim(token, domain_name):
    """Enable DKIM for a domain."""
    info(f"  2.3: Enabling DKIM for '{domain_name}'...")
    
    try:
        result = graph_post(token, f"domainDnsRecords/createDkim", {
            "domainId": domain_name
        })
        ok(f"  ✓ DKIM enabled for '{domain_name}'")
        return result
    except RuntimeError as e:
        err(f"  ✗ Failed to enable DKIM: {e}")
        return None


def add_dmarc_record(token, domain_name, dmarc_policy="quarantine"):
    """Add DMARC record (requires manual DNS entry or direct API)."""
    info(f"  2.4: Setting up DMARC for '{domain_name}'...")
    
    # DMARC record format
    dmarc_record = f"v=DMARC1; p={dmarc_policy}; rua=mailto:admin@{domain_name}; ruf=mailto:admin@{domain_name}; fo=1"
    
    info(f"  📝 Add this DMARC record to your DNS provider:")
    info(f"     Host: _dmarc.{domain_name}")
    info(f"     Type: TXT")
    info(f"     Value: {dmarc_record}")
    
    warn("  ⚠ DMARC setup must be done via your DNS provider (Cloudflare, Route53, etc.)")
    warn("     Graph API does not support direct DMARC configuration")
    
    return True


# ─── Phase 3: User Creation & Licensing ──────────────────────
def create_user(token, user_data):
    """Create a user in the tenant."""
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
    """Assign a license to a user."""
    info(f"  3.2: Assigning license to user {user_id}...")
    
    try:
        # First, get available SKUs
        skus = graph_get(token, "subscribedSkus")
        target_sku = None
        for sku in skus.get("value", []):
            if sku['skuPartNumber'] == license_sku:
                target_sku = sku
                break
        
        if not target_sku:
            warn(f"  ⚠ License '{license_sku}' not found. Available licenses: {[s['skuPartNumber'] for s in skus.get('value', [])]}")
            return False
        
        license_body = {
            "addLicenses": [
                {
                    "skuId": target_sku['skuId']
                }
            ],
            "removeLicenses": []
        }
        
        result = graph_post(token, f"users/{user_id}/assignLicense", license_body)
        ok(f"  ✓ License '{license_sku}' assigned")
        return True
    except RuntimeError as e:
        err(f"  ✗ Failed to assign license: {e}")
        return False


def bulk_create_users(token, users_list):
    """Bulk create users from JSON list."""
    info("Phase 3: User Creation & Licensing")
    
    created_users = []
    
    for user_data in users_list:
        user = create_user(token, user_data)
        if user:
            created_users.append(user)
            
            # Assign license if requested
            if user_data.get('assign_license', False):
                user_id = user.get('id')
                if user_id:
                    assign_license(token, user_id)
    
    ok(f"  ✓ Created {len(created_users)}/{len(users_list)} users")
    return created_users


# ─── Phase 4: Room Mailbox Setup ─────────────────────────────
def create_room_mailbox(token, mailbox_data):
    """Create a shared/room mailbox."""
    info(f"  4.1: Creating mailbox '{mailbox_data['email']}'...")
    
    try:
        # Create as a mail-enabled group or shared mailbox
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
    """Bulk create room mailboxes."""
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
    load_env()
    
    parser = argparse.ArgumentParser(
        description="Automated Microsoft Tenant Setup via Graph API"
    )
    parser.add_argument("--config", help="Path to JSON configuration file (optional if using .env)")
    parser.add_argument("--phase", help="Run specific phase: security, domains, users, mailboxes (default: all)")
    args = parser.parse_args()

    # Load config from file or .env
    config = {}
    
    if args.config:
        if not os.path.exists(args.config):
            err(f"Config file not found: {args.config}")
            sys.exit(1)
        with open(args.config) as f:
            config = json.load(f)

    # Override with environment variables if present
    tenant_id = config.get("tenant_id") or os.environ.get("TENANT_ID")
    client_id = config.get("client_id") or os.environ.get("CLIENT_ID")
    client_secret = config.get("client_secret") or os.environ.get("CLIENT_SECRET")

    if not all([tenant_id, client_id, client_secret]):
        err("Missing credentials. Provide via:")
        err("  1. .env file (TENANT_ID, CLIENT_ID, CLIENT_SECRET)")
        err("  2. JSON config file (--config)")
        sys.exit(1)

    info("=" * 60)
    info("  Microsoft Tenant Setup — Graph API Automation")
    info("=" * 60)
    info(f"  Tenant ID: {tenant_id}")
    info(f"  Client ID: {client_id}")
    info("=" * 60)
    info("")

    # Get token
    info("Getting access token...")
    try:
        token = get_access_token(tenant_id, client_id, client_secret)
        ok("✓ Token acquired")
    except RuntimeError as e:
        err(f"✗ Token error: {e}")
        sys.exit(1)

    info("")

    phases_to_run = args.phase.split(",") if args.phase else config.get("phases", ["security", "domains", "users", "mailboxes"])

    # Phase 1: Security
    if "security" in phases_to_run:
        try:
            setup_security_defaults(token, disable=True)
            disable_mfa_registration_campaign(token)
            disable_system_preferred_mfa(token)
            enable_smtp_auth(token, tenant_id, client_id, client_secret)
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

