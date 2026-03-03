# Internal Microsoft Mailbox Tool — Plan

## Goal (Testing Phase)
Build two scripts and test all APIs end-to-end using Google Sheets as the control panel:
1. **Script 1 (Selenium)** — Runs on your laptop. One-time tenant setup (MFA, App Registration, certificate). Writes credentials to Google Sheet.
2. **Script 2 (API)** — Simple Python scripts. Reads from Google Sheet, runs all API + PowerShell operations, updates status in the sheet.

No dashboard, no database, no server for now. Just scripts + Google Sheets.

---

## How It Works (Core Insight)
Room mailboxes in Microsoft 365 are free (no license needed) but when created
with `EnableRoomMailboxAccount = true`, they have a real user account behind them
that can:
- Log in directly
- Authenticate via SMTP
- Connect to Instantly.ai independently

So per tenant:
- 1 license (admin account only)
- 50 room mailboxes (free, no extra licenses)
- Each room mailbox has SMTP AUTH enabled
- Each connects to Instantly as a separate sending account

---

## Architecture (Testing Phase)

```
┌─────────────────────────────────────────┐
│  SCRIPT 1 — Selenium (Your Laptop)      │
│  • Login + MFA                           │
│  • App Registration + certificate        │
│  • Writes credentials to Google Sheet   │
└──────────────────┬──────────────────────┘
                   │
            Google Sheet
         (single source of truth)
                   │
┌──────────────────┴──────────────────────┐
│  SCRIPT 2 — API Scripts (Your Laptop)   │
│  • Reads tenant info from Google Sheet  │
│  • Runs API calls step by step          │
│  • Updates status in Google Sheet       │
│  • Each step is a separate command      │
└─────────────────────────────────────────┘
```

---

## Tech Stack (Testing Phase)

| Component | Technology | Why |
|-----------|-----------|-----|
| Script 1 | Python + Selenium | Browser automation for MFA |
| Script 2 | Python + requests | API calls |
| PowerShell | pwsh via subprocess | Room mailboxes + SMTP AUTH |
| Control Panel | Google Sheets + gspread | Simple, visual, no setup |
| DNS | Cloudflare API | DNS record management |

---

## Google Sheet Structure

### Sheet 1: Tenants
| admin_email | admin_password | tenant_id | client_id | client_secret | cert_base64 | cert_password | license_assigned | org_smtp_enabled | status |
|-------------|---------------|-----------|-----------|---------------|-------------|---------------|-----------------|-----------------|--------|
| admin@tenant.com | Pass123 | 58882... | xxx-xxx | xxxxx | MIIC... | auto123 | ✅ | ✅ | active |

### Sheet 2: Domains
| tenant_id | domain | cloudflare_zone_id | verified | spf | dkim | dmarc | status |
|-----------|--------|-------------------|----------|-----|------|-------|--------|
| 58882... | godaltonhq.co | abc123 | ✅ | ✅ | ✅ | ✅ | active |

### Sheet 3: Mailboxes
| tenant_id | domain | email | password | display_name | smtp_enabled | instantly_added | status |
|-----------|--------|-------|----------|-------------|-------------|----------------|--------|
| 58882... | godaltonhq.co | vincent@godaltonhq.co | Pass123 | Vincent Declercq | ✅ | ✅ | active |

---

# SCRIPT 1 — Selenium Setup (Your Laptop)

## What It Does
One-time per tenant: logs in, handles MFA, disables security settings,
creates App Registration with all permissions, generates certificate,
and writes credentials to Google Sheet.

## Usage
```bash
# Single tenant
python setup_tenant.py --email admin@tenant.com --password P@ss123

# Multiple tenants from CSV
python setup_tenant.py --csv tenants.csv
```

## Per Tenant Steps (Automated via Selenium)

### 1.1 — Login + Handle MFA
```
→ Opens admin.microsoft.com
→ Enters admin email + password
→ If MFA prompt appears:
  → Uses authenticator browser extension to complete MFA
```

### 1.2 — Disable All MFA Settings
```
→ Goes to entra.microsoft.com:
  → Overview > Properties > Manage security defaults > Disabled
  → Authentication methods > Registration campaign > State: Disabled
  → Authentication methods > Settings > System-preferred MFA: Disabled

→ Goes to myaccount.microsoft.com:
  → Security info > Deletes all TOTP / recovery email entries
```

### 1.3 — Create App Registration
```
→ Extracts bearer token from browser session (MSAL cache in sessionStorage)
→ Uses token to call Graph API:

POST https://graph.microsoft.com/v1.0/applications
{
  "displayName": "MailboxTool-{tenant_name}",
  "signInAudience": "AzureADMyOrg"
}
→ Gets back application_id (client_id)

→ Creates client secret:
POST https://graph.microsoft.com/v1.0/applications/{app_id}/addPassword
{
  "passwordCredential": {"displayName": "auto-generated", "endDateTime": "2028-01-01T00:00:00Z"}
}
→ Gets back client_secret
```

### 1.4 — Generate + Upload Certificate
```
→ Python cryptography library generates self-signed X.509 certificate
→ Saves .pfx file locally
→ Uploads public key to App Registration:
PATCH https://graph.microsoft.com/v1.0/applications/{app_id}
{
  "keyCredentials": [{"type": "AsymmetricX509Cert", "usage": "Verify", "key": "base64_cert"}]
}
```

### 1.5 — Assign API Permissions + Admin Consent
```
→ Adds required API permissions:
PATCH https://graph.microsoft.com/v1.0/applications/{app_id}
{
  "requiredResourceAccess": [
    {
      "resourceAppId": "00000003-0000-0000-c000-000000000000",  // Graph API
      "resourceAccess": [
        {"id": "...", "type": "Role"},  // User.ReadWrite.All
        {"id": "...", "type": "Role"},  // Directory.ReadWrite.All
        {"id": "...", "type": "Role"},  // Domain.ReadWrite.All
        {"id": "...", "type": "Role"},  // Organization.ReadWrite.All
        {"id": "...", "type": "Role"},  // Reports.Read.All
        {"id": "...", "type": "Role"},  // Application.ReadWrite.All
      ]
    },
    {
      "resourceAppId": "00000002-0000-0ff1-ce00-000000000000",  // Exchange Online
      "resourceAccess": [
        {"id": "dc50a0fb-09a3-484d-be87-e023b12c6440", "type": "Role"}  // Exchange.ManageAsApp
      ]
    }
  ]
}

→ Grants admin consent:
POST https://graph.microsoft.com/v1.0/servicePrincipals/{sp_id}/appRoleAssignments
(for each permission)
```

### 1.6 — Assign Exchange Administrator Role
```
→ Gets the service principal ID for the app
→ Assigns Exchange Administrator directory role:
POST https://graph.microsoft.com/v1.0/directoryRoles/{exchange_admin_role_id}/members/$ref
{
  "@odata.id": "https://graph.microsoft.com/v1.0/servicePrincipals/{sp_id}"
}
```

### 1.7 — Write to Google Sheet
```
→ Writes a new row to the "Tenants" sheet:
  admin_email, admin_password, tenant_id, client_id, client_secret,
  cert_base64, cert_password, status = "setup_complete"
```

## Script 1 Folder Structure
```
selenium-setup/
├── setup_tenant.py          ← main entry point
├── browser.py               ← Selenium browser management
├── mfa_handler.py           ← MFA detection + authenticator extension
├── security_settings.py     ← disable MFA/security defaults
├── app_registration.py      ← Graph API calls for app reg + permissions
├── cert_generator.py        ← certificate generation + upload
├── role_assignment.py       ← Exchange Administrator role assignment
├── sheets.py                ← Google Sheets read/write
├── config.py                ← settings
├── requirements.txt         ← selenium, cryptography, requests, gspread
└── output/                  ← backup JSON per tenant
    └── {tenant_name}.json
```

---

# SCRIPT 2 — API Scripts (Your Laptop)

## What It Does
Reads tenant credentials from Google Sheet, runs each step via API/PowerShell,
updates the sheet after each step. Each step is a separate CLI command so you
can test them individually.

## Usage
```bash
# Run a specific step for a specific tenant
python run.py assign-license --tenant admin@tenant.com
python run.py enable-org-smtp --tenant admin@tenant.com
python run.py add-domain --tenant admin@tenant.com --domain godaltonhq.co
python run.py verify-domain --tenant admin@tenant.com --domain godaltonhq.co
python run.py setup-spf --tenant admin@tenant.com --domain godaltonhq.co
python run.py setup-dkim --tenant admin@tenant.com --domain godaltonhq.co
python run.py setup-dmarc --tenant admin@tenant.com --domain godaltonhq.co
python run.py create-mailboxes --tenant admin@tenant.com --domain godaltonhq.co --count 50
python run.py enable-smtp --tenant admin@tenant.com
python run.py add-to-instantly --tenant admin@tenant.com

# Run ALL steps for a tenant (full pipeline)
python run.py full-pipeline --tenant admin@tenant.com --domain godaltonhq.co

# Run a step for ALL tenants in the sheet
python run.py assign-license --all
```

## Steps

### Step 1 — Assign License to Admin (Graph API)
```python
# Reads: tenant_id, client_id, client_secret from Google Sheet
# Calls:
POST https://graph.microsoft.com/v1.0/users/{admin_id}/assignLicense
{
  "addLicenses": [{"skuId": "{available_sku_id}"}],
  "removeLicenses": []
}
# Updates: license_assigned = ✅ in Google Sheet
```

### Step 2 — Org-Level SMTP AUTH (Exchange PowerShell)
```powershell
Connect-ExchangeOnline -AppId '{client_id}'
                       -CertificateFilePath '{cert_path}'
                       -Organization '{tenant}'
Set-TransportConfig -SmtpClientAuthenticationDisabled $false
Disconnect-ExchangeOnline -Confirm:$false
```
```
# Updates: org_smtp_enabled = ✅ in Google Sheet
```

### Step 3 — Add Custom Domain (Graph API + Cloudflare API)

#### 3.1 — Add domain to Microsoft tenant
```python
POST https://graph.microsoft.com/v1.0/domains
{"id": "godaltonhq.co"}

GET https://graph.microsoft.com/v1.0/domains/{domain}/verificationDnsRecords
```

#### 3.2 — Add verification record to Cloudflare
```python
POST https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records
{
  "type": "TXT",
  "name": "@",
  "content": "MS=ms12345678"
}
```

#### 3.3 — Verify domain in Microsoft
```python
POST https://graph.microsoft.com/v1.0/domains/{domain}/verify
```
Note: May need to wait for DNS propagation. Script retries automatically.

#### 3.4 — Add Exchange DNS records to Cloudflare
```
MX      → {domain}.mail.protection.outlook.com (priority 0)
TXT     → v=spf1 include:spf.protection.outlook.com -all  (SPF)
CNAME   → autodiscover.{domain} → autodiscover.outlook.com
```
```
# Updates: Domains sheet — verified = ✅, spf = ✅
```

### Step 4 — Enable DKIM (Graph API + Cloudflare)
```python
GET https://graph.microsoft.com/v1.0/security/dkimSigningConfigs/{domain}

# Add DKIM CNAME records to Cloudflare:
# selector1._domainkey.{domain} → selector1-{domain}._domainkey.{tenant}.onmicrosoft.com
# selector2._domainkey.{domain} → selector2-{domain}._domainkey.{tenant}.onmicrosoft.com

PATCH https://graph.microsoft.com/v1.0/security/dkimSigningConfigs/{domain}
{"isEnabled": true}
```
```
# Updates: Domains sheet — dkim = ✅
```

### Step 5 — Add DMARC Record (Cloudflare API)
```python
POST https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records
{
  "type": "TXT",
  "name": "_dmarc",
  "content": "v=DMARC1; p=none; rua=mailto:dmarc@{domain}"
}
```
```
# Updates: Domains sheet — dmarc = ✅
```

### Step 6 — Create 50 Room Mailboxes (Exchange PowerShell)
```powershell
# Connect ONCE, create all 50, then disconnect
Connect-ExchangeOnline -AppId '{client_id}'
                       -CertificateFilePath '{cert_path}'
                       -Organization '{tenant}'

# Loop through all mailboxes:
New-Mailbox -Name '{first_name} {last_name}'
            -Alias '{alias}'
            -Room
            -EnableRoomMailboxAccount $true
            -MicrosoftOnlineServicesID '{email}@{domain}'
            -RoomMailboxPassword (ConvertTo-SecureString '{password}' -AsPlainText -Force)

Disconnect-ExchangeOnline -Confirm:$false
```
```
# Mailbox names/passwords are generated or read from a separate input
# Updates: Mailboxes sheet — adds 50 rows with status = created
```

### Step 7 — Enable SMTP AUTH Per Mailbox (Exchange PowerShell)
```powershell
# Connect ONCE, enable for all 50, then disconnect
Connect-ExchangeOnline -AppId '{client_id}'
                       -CertificateFilePath '{cert_path}'
                       -Organization '{tenant}'

# Loop:
Set-CASMailbox -Identity '{email}' -SmtpClientAuthenticationDisabled $false

Disconnect-ExchangeOnline -Confirm:$false
```
```
# Updates: Mailboxes sheet — smtp_enabled = ✅
```

### Step 8 — Add to Instantly
```
IMPORTANT: First user per tenant MUST be added manually to Instantly
and granted OAuth permissions before running this step.

After first user is granted:
python run.py add-to-instantly --tenant admin@tenant.com
```
```
# Updates: Mailboxes sheet — instantly_added = ✅
```

### Pipeline Order
```
assign-license
  → enable-org-smtp
    → add-domain
      → verify-domain
        → setup-spf (done as part of add-domain)
          → setup-dkim
            → setup-dmarc
              → create-mailboxes
                → enable-smtp
                  → [manual: grant Instantly OAuth for first user]
                    → add-to-instantly
```

---

## Email Authentication Summary (Critical for Deliverability)

| Record | Purpose | Where Added | How |
|--------|---------|-------------|-----|
| SPF | Declares which servers can send for domain | Cloudflare TXT | `v=spf1 include:spf.protection.outlook.com -all` |
| DKIM | Cryptographic signature on emails | Cloudflare CNAME x 2 | Microsoft generates keys, we add CNAME records |
| DMARC | Policy for handling failed SPF/DKIM | Cloudflare TXT | `v=DMARC1; p=none; rua=mailto:dmarc@{domain}` |

---

## App Registration Permissions (Created by Script 1)

### API Permissions (Application type):
| Permission | Type | For |
|-----------|------|-----|
| User.ReadWrite.All | Application | Create/manage users |
| Directory.ReadWrite.All | Application | Read directory data |
| Application.ReadWrite.All | Application | Manage app registrations |
| Domain.ReadWrite.All | Application | Add/verify domains |
| Organization.ReadWrite.All | Application | Org settings |
| Exchange.ManageAsApp | Application | Exchange PowerShell app-only |
| Reports.Read.All | Application | Mailflow reports (for later) |

### Azure AD Role Assignment:
| Role | For |
|------|-----|
| Exchange Administrator | Required for Exchange PS app-only auth |

---

## Folder Structure

```
project/
│
├── selenium-setup/                     ← SCRIPT 1 (your laptop)
│   ├── setup_tenant.py                 ← main entry point
│   ├── browser.py                      ← Selenium browser management
│   ├── mfa_handler.py                  ← MFA detection + authenticator extension
│   ├── security_settings.py            ← disable MFA/security defaults
│   ├── app_registration.py             ← Graph API calls for app reg + permissions
│   ├── cert_generator.py               ← certificate generation + upload
│   ├── role_assignment.py              ← Exchange Administrator role assignment
│   ├── sheets.py                       ← Google Sheets read/write
│   ├── config.py                       ← settings (sheet ID, etc.)
│   ├── requirements.txt
│   └── output/                         ← backup JSON per tenant
│       └── {tenant_name}.json
│
├── api-scripts/                        ← SCRIPT 2 (your laptop for testing)
│   ├── run.py                          ← main CLI entry point
│   ├── steps/
│   │   ├── assign_license.py           ← Graph API license assignment
│   │   ├── enable_org_smtp.py          ← Exchange PS org-level SMTP
│   │   ├── add_domain.py              ← Graph API + Cloudflare domain setup
│   │   ├── verify_domain.py           ← Graph API domain verification
│   │   ├── setup_dkim.py             ← Graph API + Cloudflare DKIM
│   │   ├── setup_dmarc.py            ← Cloudflare DMARC
│   │   ├── create_mailboxes.py        ← Exchange PowerShell room mailboxes
│   │   ├── enable_smtp.py             ← Exchange PowerShell SMTP AUTH
│   │   └── add_to_instantly.py        ← Instantly integration
│   ├── services/
│   │   ├── graph_api.py               ← Microsoft Graph API client
│   │   ├── powershell.py              ← PowerShell subprocess wrapper
│   │   ├── cloudflare.py              ← Cloudflare API client
│   │   └── instantly.py               ← Instantly integration
│   ├── sheets.py                       ← Google Sheets read/write
│   ├── config.py                       ← settings (sheet ID, Cloudflare key, etc.)
│   └── requirements.txt
│
└── README.md
```

---

## Prerequisites (Your Laptop)
- Python 3.10+
- Chrome/Chromium + ChromeDriver (for Script 1)
- Authenticator browser extension (for Script 1)
- PowerShell Core: `brew install --cask powershell`
- Exchange Online PowerShell module: `Install-Module -Name ExchangeOnlineManagement` (inside pwsh)
- Google Cloud service account JSON key (for gspread)
- Cloudflare API key
- Instantly.ai credentials

---

## Development Phases (Testing)

### Phase 1 — Setup
- Create Google Sheet with 3 tabs (Tenants, Domains, Mailboxes)
- Setup Google Cloud service account for Sheets API
- Install PowerShell Core + ExchangeOnlineManagement module
- Setup Python virtual env + install dependencies

### Phase 2 — Script 1 (Selenium)
- Build and test each step one at a time:
  1. Login + MFA handling
  2. Disable security defaults
  3. Create App Registration
  4. Generate certificate
  5. Assign permissions + admin consent
  6. Assign Exchange Administrator role
  7. Write to Google Sheet
- Test end-to-end on TourmalineOspreyPeak tenant

### Phase 3 — Script 2 (API Scripts)
- Build and test each step individually:
  1. assign-license (Graph API)
  2. enable-org-smtp (Exchange PowerShell)
  3. add-domain (Graph API + Cloudflare)
  4. verify-domain (Graph API)
  5. setup-dkim (Graph API + Cloudflare)
  6. setup-dmarc (Cloudflare)
  7. create-mailboxes (Exchange PowerShell)
  8. enable-smtp (Exchange PowerShell)
  9. add-to-instantly (Instantly)
- Test full pipeline end-to-end on one tenant

### Phase 4 — Batch Testing
- Test Script 1 with 5 tenants
- Test Script 2 full pipeline with 5 tenants
- Fix any rate limiting or timing issues

### Future — Dashboard (After APIs are validated)
- Move from Google Sheets to PostgreSQL
- Build FastAPI backend + Celery workers
- Build Next.js dashboard
- Add monitoring + alerts

---

## Notes
- Google Sheets = temporary control panel for testing
- Each API step can be run individually for debugging
- Script 1 (Selenium) is completely independent from Script 2
- PowerShell connects ONCE per batch for efficiency
- Room mailboxes = free, loginable, SMTP-capable
- 1 license (admin) + 50 room mailboxes per tenant
- SPF + DKIM + DMARC all required per domain
- First user per tenant needs manual Instantly OAuth grant
- Once all APIs are validated, will build full dashboard
