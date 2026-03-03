# Microsoft Tenant Setup Automation

Automates Microsoft 365 tenant configuration using Graph API and Exchange Online API.

## Quick Start

### Step 1: Install Azure CLI (One-time)

```powershell
winget install Microsoft.AzureCLI
```

### Step 2: Run Setup Script

```powershell
.\setup_azure_app.ps1
```

**What it does:**
1. Opens browser → Select your admin account
2. Creates app registration with all permissions
3. Grants admin consent
4. Assigns Exchange Administrator role
5. Saves credentials to `.env` file
6. Updates Google Sheet (if configured)

### Step 3: Wait 5 Minutes

### Step 4: Run Automation

```powershell
python tenant_setup_automation.py
```

---

## Google Sheet Integration

### Your Sheet Columns (Settings tab):

| A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|
| ... | ... | ... | ADMIN_EMAIL | TENANT_ID | CLIENT_ID | CLIENT_SECRET |

The script finds the row with your admin email and updates columns E, F, G.

### To Enable Sheet Updates:

1. Create Google Cloud service account
2. Download JSON key → save as `service_account.json`
3. Share your Google Sheet with service account email
4. Run: `python update_sheet.py`

---

## Files

| File | Purpose |
|------|---------|
| `setup_azure_app.ps1` | Creates Azure app + permissions |
| `setup_azure_app.bat` | Easy launcher |
| `tenant_setup_automation.py` | Main automation |
| `update_sheet.py` | Update Google Sheet |
| `.env` | Your credentials |

---

## What Gets Automated

| Task | Status |
|------|--------|
| Disable Security Defaults | ✅ |
| Disable MFA Registration | ✅ |
| Disable System MFA | ✅ |
| Enable SMTP AUTH | ✅ |
| Add/Verify Domains | ✅ |
| Create Users | ✅ |
| Assign Licenses | ✅ |
| Create Mailboxes | ✅ |

---

## Commands

```powershell
# Full setup (one command)
.\setup_azure_app.ps1

# Run tenant automation
python tenant_setup_automation.py

# Run specific phase
python tenant_setup_automation.py --phase security
python tenant_setup_automation.py --phase domains

# Update Google Sheet
python update_sheet.py
```
