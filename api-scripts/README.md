# Microsoft 365 Tenant Pipeline — Script 2 (`api-scripts/`)

Automated pipeline that configures a Microsoft 365 tenant for email sending: assigns licenses, adds a custom domain with full DNS setup (MX, SPF, DKIM, DMARC), creates room mailboxes, and enables SMTP AUTH.

## Prerequisites

- **Python 3.8+**
- **PowerShell 7+** (`pwsh`) — required for Exchange Online steps
- **ExchangeOnlineManagement** PowerShell module — auto-installed if missing
- **Cloudflare account** — for DNS record management
- **Completed Script 1** (`selenium-setup/`) — provides tenant credentials and app registration

## Directory Structure

```
api-scripts/
├── run.py                  # CLI entry point
├── config.py               # Paths, API URLs, defaults
├── log.py                  # Shared logging (info/ok/warn/err)
├── tenant_loader.py        # Loads tenant credentials from selenium-setup output
├── name_generator.py       # Generates mailbox identities (names + passwords)
├── services/
│   ├── graph_api.py        # Microsoft Graph API client (v1.0 + beta)
│   ├── cloudflare.py       # Cloudflare DNS API client
│   └── powershell.py       # PowerShell runner with Exchange Online auth
├── steps/
│   ├── assign_license.py               # Step 1
│   ├── enable_org_smtp.py              # Step 2
│   ├── add_domain.py                   # Step 3
│   ├── verify_domain.py               # Step 4
│   ├── setup_dkim.py                   # Step 5
│   ├── setup_dmarc.py                  # Step 6
│   ├── create_mailboxes.py             # Step 7
│   ├── enable_smtp.py                  # Step 8
│   └── disable_calendar_processing.py  # Step 9
└── output/                 # Generated output files
```

## Setup

### 1. Environment Variables

Set Cloudflare credentials (or they'll fall back to defaults in `config.py`):

```bash
export CLOUDFLARE_API_KEY="your-global-api-key"
export CLOUDFLARE_EMAIL="your-cloudflare-email"
```

### 2. Selenium Setup Output

Ensure Script 1 (`selenium-setup/`) has been run for the target tenant. This produces:

```
selenium-setup/output/{TenantName}/
├── credentials.json    # tenant_id, client_id, client_secret, admin credentials
└── cert.pfx            # Certificate for Exchange Online PowerShell auth
```

## Usage

### Run a single step

```bash
cd api-scripts
python run.py assign-license --tenant MoonstoneDarterInlet
python run.py add-domain --tenant MoonstoneDarterInlet --domain phytoblade.info
python run.py create-mailboxes --tenant MoonstoneDarterInlet --domain phytoblade.info --count 25
```

### Run the full pipeline

```bash
python run.py full-pipeline --tenant MoonstoneDarterInlet --domain phytoblade.info
```

### Resume from a specific step

```bash
python run.py full-pipeline --tenant MoonstoneDarterInlet --domain phytoblade.info --start-from setup-dkim
```

### Show help

```bash
python run.py --help
python run.py full-pipeline --help
```

## Pipeline Steps

| # | Step | Description |
|---|------|-------------|
| 1 | `assign-license` | Assigns an available license (e.g. Exchange Online) to the admin user |
| 2 | `enable-org-smtp` | Enables SMTP AUTH at the organisation level via PowerShell (`Set-TransportConfig`) |
| 3 | `add-domain` | Adds the custom domain to the tenant and creates DNS records in Cloudflare (TXT verification, MX, SPF, autodiscover CNAME) |
| 4 | `verify-domain` | Verifies the domain in Microsoft 365 with retries and exponential backoff for DNS propagation |
| 5 | `setup-dkim` | Creates DKIM CNAME records (selector1, selector2) in Cloudflare and enables DKIM signing |
| 6 | `setup-dmarc` | Creates a DMARC TXT record (`_dmarc.{domain}`) in Cloudflare |
| 7 | `create-mailboxes` | Creates room mailboxes via PowerShell (`New-Mailbox -Room`). Default: 50 mailboxes. Outputs JSON + CSV |
| 8 | `enable-smtp` | Enables per-mailbox SMTP AUTH via PowerShell (`Set-CASMailbox`) |
| 9 | `disable-calendar-processing` | Disables calendar auto-processing (`Set-CalendarProcessing -AutomateProcessing None`) so mailboxes work as normal inboxes |

## Output Files

All output is written to `api-scripts/output/`:

| File | Description |
|------|-------------|
| `{tenant}_pipeline.json` | Pipeline progress tracker — records status and timestamp for each completed step |
| `{tenant}_mailboxes.json` | Full mailbox data: identities (name, email, password) and creation results |
| `{tenant}_mailboxes.csv` | CSV export of mailbox credentials (`first_name,last_name,display_name,email,password`) |

## Known Issues & Workarounds

### Graph beta API unreliability
The Graph beta endpoints for `transportConfig` and `dkimSigningConfigs` are unreliable. The pipeline tries PowerShell first and only falls back to Graph beta.

### DNS propagation delays
Domain verification (Step 4) and DKIM enabling (Step 5) may fail on the first attempt due to DNS propagation. Both steps include automatic retries with exponential backoff. If they still fail, wait a few minutes and re-run the step.

### Room mailbox calendar processing
Room mailboxes default to `AutomateProcessing=AutoAccept` which deletes email content (comments, subject). Step 9 disables this so they behave as normal inboxes.

### Proxy address conflicts
If a mailbox email is already in use (e.g. from a previous partial run), `create-mailboxes` detects the "proxy address already being used" error and reports it as `EXISTS` instead of failing.

### Instantly admin consent
After the pipeline completes, the tenant may still need admin consent granted in the Instantly dashboard for SMTP sending to work.
