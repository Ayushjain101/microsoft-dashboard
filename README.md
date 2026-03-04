# Microsoft Tenant Setup Tool

Automated Microsoft 365 tenant provisioning dashboard. Handles the full lifecycle: tenant login via Selenium, Azure app registration, certificate generation, MFA enrollment, mailbox creation via PowerShell, DNS configuration via Cloudflare, and ongoing SMTP/DNS health monitoring.

## Architecture Overview

```
                         ┌──────────────────────────────────┐
                         │         Caddy (HTTPS)            │
                         │   decimastellarbolt.info          │
                         └──────┬───────────────┬───────────┘
                                │               │
                     /api/* /ws/*          everything else
                                │               │
                   ┌────────────▼──┐    ┌───────▼──────────┐
                   │  FastAPI :8000│    │  Next.js :3000    │
                   │  (backend)    │    │  (frontend)       │
                   └──┬────┬───┬──┘    └───────────────────┘
                      │    │   │
              ┌───────┘    │   └────────────┐
              │            │                │
     ┌────────▼──┐  ┌─────▼─────┐  ┌───────▼───────┐
     │ PostgreSQL │  │   Redis   │  │ Celery Workers │
     │  (models)  │  │ (broker + │  │  4 queues:     │
     │            │  │  pub/sub) │  │  default,      │
     └────────────┘  └───────────┘  │  tenant_setup, │
                                    │  mailbox,      │
                                    │  monitor       │
                                    └───────┬───────┘
                                            │
                              ┌─────────────┼──────────────┐
                              │             │              │
                    ┌─────────▼──┐  ┌───────▼───┐  ┌──────▼─────┐
                    │  Selenium   │  │ PowerShell│  │  Cloudflare│
                    │  + Chrome   │  │  (pwsh)   │  │    API     │
                    │  + Xvfb     │  │ Exchange  │  │   (DNS)    │
                    └─────────────┘  └───────────┘  └────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI 0.115, Python 3.11+, Uvicorn |
| Database | PostgreSQL 16, SQLAlchemy 2.0 (async), Alembic migrations |
| Task Queue | Celery 5.4 with Redis broker, Celery Beat scheduler |
| Browser Automation | Selenium 4.27 + Chrome + Xvfb (headless) |
| Shell Automation | PowerShell 7 (pwsh) + Exchange Online module |
| Frontend | Next.js 15.1, React 19, TypeScript, Tailwind CSS |
| Reverse Proxy | Caddy 2 (auto HTTPS via Let's Encrypt) |
| Encryption | Fernet symmetric encryption (cryptography lib) |
| Real-time | WebSocket via Redis pub/sub relay |

---

## Directory Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, router registration
│   │   ├── config.py                # Pydantic Settings (env vars)
│   │   ├── database.py              # Async SQLAlchemy engine + session
│   │   ├── models.py                # All SQLAlchemy ORM models
│   │   ├── security.py              # Session management (Redis-backed)
│   │   ├── websocket.py             # WebSocket manager (Redis pub/sub relay)
│   │   ├── api/
│   │   │   ├── auth.py              # POST /login, /logout, GET /verify
│   │   │   ├── deps.py              # FastAPI dependencies (get_db, require_auth)
│   │   │   ├── tenants.py           # CRUD + setup/retry for tenants
│   │   │   ├── mailboxes.py         # Mailbox CRUD + job management
│   │   │   ├── monitor.py           # Health dashboard, alerts, checks
│   │   │   ├── settings.py          # Cloudflare configs, alert settings
│   │   │   ├── totp.py              # TOTP vault (live MFA codes)
│   │   │   └── ws.py                # WebSocket endpoint /ws/live
│   │   ├── services/
│   │   │   ├── encryption.py        # Fernet encrypt/decrypt helpers
│   │   │   ├── graph_client.py      # Microsoft Graph API client (OAuth2 CC flow)
│   │   │   ├── cloudflare_client.py # Cloudflare DNS CRUD
│   │   │   ├── powershell.py        # PowerShell subprocess runner (Exchange)
│   │   │   └── name_generator.py    # Random mailbox identity generator
│   │   ├── tasks/
│   │   │   ├── celery_app.py        # Celery config, queue routing, beat schedule
│   │   │   ├── tenant_setup.py      # 12-step tenant setup task
│   │   │   ├── mailbox_pipeline.py  # 9-step mailbox creation pipeline
│   │   │   └── monitor.py           # SMTP/DNS health checks, stale task reaper
│   │   └── selenium_worker/
│   │       ├── setup_tenant.py      # Orchestrator: runs all 12 setup steps
│   │       ├── mfa_handler.py       # Azure CLI login, MFA enrollment, device code flow
│   │       ├── app_registration.py  # Graph API: app reg, SP, secret, cert, permissions
│   │       ├── cert_generator.py    # X.509 self-signed cert generation (PEM + PFX)
│   │       ├── security_settings.py # Security defaults, CAP policies
│   │       └── browser.py           # Selenium WebDriver init + helpers
│   ├── requirements.txt
│   └── alembic/                     # Database migrations
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx             # Root → redirect to /tenants
│   │   │   ├── layout.tsx           # Root layout
│   │   │   ├── login/page.tsx       # Login form
│   │   │   ├── tenants/page.tsx     # Tenant list (main dashboard)
│   │   │   ├── tenants/new/page.tsx # Create tenant form
│   │   │   ├── mailboxes/page.tsx   # All mailboxes list
│   │   │   ├── mailboxes/[tenantId]/page.tsx  # Tenant mailboxes + create job
│   │   │   ├── monitor/page.tsx     # Health monitoring dashboard
│   │   │   ├── monitor/[tenantId]/page.tsx    # Tenant health history
│   │   │   ├── settings/page.tsx    # Cloudflare & alert settings
│   │   │   └── totp/page.tsx        # TOTP vault (live 6-digit codes)
│   │   ├── components/
│   │   │   ├── layout/AuthGuard.tsx # Auth wrapper with sidebar
│   │   │   ├── layout/Sidebar.tsx   # Navigation sidebar
│   │   │   └── tenants/SetupProgress.tsx  # Step progress display
│   │   ├── hooks/
│   │   │   ├── useAuth.ts           # Auth state + redirect to /login
│   │   │   └── useWebSocket.ts      # WebSocket connection to /ws/live
│   │   └── lib/
│   │       ├── api.ts               # HTTP client (all API methods)
│   │       └── types.ts             # TypeScript interfaces
│   ├── package.json
│   ├── next.config.ts               # output: "standalone"
│   └── tailwind.config.ts
├── .env.example                     # Environment variable template
├── Caddyfile                        # Reverse proxy config
├── deploy.sh                        # Full deployment script (systemd)
├── docker-compose.yml               # Docker setup (alternative)
├── docker-compose.selenium.yml      # Selenium Grid (alternative)
└── migrate_from_sheet.py            # One-time migration from Google Sheets
```

---

## Database Models

All models defined in `backend/app/models.py`. Sensitive fields use Fernet encryption (stored as `LargeBinary`).

### Tenant
Primary entity. Stores Microsoft 365 admin credentials and Azure app registration outputs.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| name | String(100) | Tenant display name |
| admin_email | String(255) | Microsoft admin email (unique) |
| admin_password | LargeBinary | Encrypted |
| new_password | LargeBinary | Encrypted, nullable |
| tenant_id_ms | LargeBinary | Encrypted Azure tenant ID |
| client_id | LargeBinary | Encrypted app client ID |
| client_secret | LargeBinary | Encrypted app client secret |
| cert_pfx | LargeBinary | Encrypted PFX certificate |
| cert_password | LargeBinary | Encrypted cert password |
| mfa_secret | LargeBinary | Encrypted TOTP secret |
| status | String(20) | pending / queued / running / complete / failed |
| current_step | String(200) | Current setup step description |
| error_message | Text | Last error message |
| created_at | DateTime | UTC timestamp |
| completed_at | DateTime | UTC, nullable |

**Relations**: `domains[]`, `mailboxes[]`, `mailbox_jobs[]`

### Domain
Domains added to a tenant for mailbox creation.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| tenant_id | UUID | FK → Tenant (cascade delete) |
| domain | String(255) | e.g. example.com |
| is_verified | Boolean | Domain ownership verified |
| dkim_enabled | Boolean | DKIM selectors configured |
| dmarc_created | Boolean | DMARC TXT record created |

### Mailbox
Individual email accounts created on a tenant.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| tenant_id | UUID | FK → Tenant (cascade delete) |
| domain_id | UUID | FK → Domain, nullable |
| display_name | String(200) | Full name |
| email | String(255) | Email address (unique) |
| password | LargeBinary | Encrypted |
| smtp_enabled | Boolean | SMTP AUTH enabled |
| last_monitor_status | String(20) | healthy / auth_failed / blocked / timeout |
| last_monitor_at | DateTime | Last health check |

### MailboxJob
Tracks mailbox creation pipeline runs.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| tenant_id | UUID | FK → Tenant (cascade delete) |
| domain | String(255) | Target domain |
| mailbox_count | Integer | Number of mailboxes to create |
| cf_email | String(255) | Cloudflare email for DNS |
| cf_api_key | LargeBinary | Encrypted Cloudflare API key |
| status | String(20) | queued / running / complete / failed / stopped |
| current_phase | String(200) | Current pipeline step |
| celery_task_id | String(255) | For task revocation |

### MonitorCheck
Health check results for tenants and mailboxes.

| Column | Type | Notes |
|--------|------|-------|
| id | BigInteger | Auto-increment PK |
| tenant_id | UUID | FK → Tenant |
| mailbox_id | UUID | FK → Mailbox, nullable |
| check_type | String(30) | smtp_send / dns |
| status | String(20) | healthy / auth_failed / blocked / timeout / error |
| detail | Text | Error details |
| response_ms | Integer | Response time |

### Alert
Monitoring alerts for tenant issues.

| Column | Type | Notes |
|--------|------|-------|
| id | BigInteger | Auto-increment PK |
| tenant_id | UUID | FK → Tenant |
| alert_type | String(50) | smtp_blocked, dns_issue, etc. |
| severity | String(10) | critical / warning / info |
| message | Text | Alert description |
| acknowledged | Boolean | Has been seen |

### CloudflareConfig
Stored Cloudflare API credentials for DNS management.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| label | String(100) | Display label |
| cf_email | String(255) | Cloudflare account email |
| cf_api_key | LargeBinary | Encrypted API key |
| is_default | Boolean | Use by default for new jobs |

### AppSetting
Key-value store for application settings (webhook URLs, check intervals).

| Column | Type | Notes |
|--------|------|-------|
| key | String(100) | Primary key |
| value | Text | Setting value |

---

## API Endpoints

Base URL: `/api/v1`

### Authentication (`/api/v1/auth`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/login` | Login with dashboard password. Sets `session_token` httponly cookie |
| POST | `/logout` | Destroy session, clear cookie |
| GET | `/verify` | Check if session is valid (returns 200 or 401) |

### Tenants (`/api/v1/tenants`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List tenants. Query: `page`, `per_page`, `status_filter` |
| POST | `/` | Create tenant. Body: `{name, admin_email, admin_password, new_password?}` |
| POST | `/bulk` | Bulk create from CSV/JSON upload (multipart file) |
| GET | `/{tenant_id}` | Get tenant with decrypted credentials |
| GET | `/{tenant_id}/credentials` | Download credentials as JSON |
| POST | `/{tenant_id}/setup` | Queue Celery task for 12-step setup |
| POST | `/{tenant_id}/retry` | Retry failed setup (resets status to queued) |
| DELETE | `/{tenant_id}` | Delete tenant and all related data |

**Important**: Routes `/{tenant_id}/credentials`, `/{tenant_id}/setup`, `/{tenant_id}/retry` are registered before the `/{tenant_id}` catch-all to avoid route shadowing.

### Mailboxes (`/api/v1/mailboxes`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all mailboxes (paginated) |
| GET | `/{tenant_id}` | List mailboxes for a specific tenant |
| GET | `/{tenant_id}/export` | Export tenant's mailboxes as CSV |
| POST | `/{tenant_id}/create` | Create mailbox job. Body: `{domain, mailbox_count, cf_email?, cf_api_key?}` |

### Mailbox Jobs (`/api/v1/mailbox-jobs`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all mailbox jobs |
| POST | `/{job_id}/stop` | Stop a running job (revokes Celery task) |

### Monitor (`/api/v1/monitor`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Health summary: tenant/mailbox counts, check stats |
| GET | `/alerts` | List alerts. Query: `acknowledged` (bool) |
| POST | `/alerts/{alert_id}/ack` | Acknowledge an alert |
| GET | `/{tenant_id}` | Health check history for a tenant |
| POST | `/{tenant_id}/check-now` | Trigger immediate SMTP/DNS check |

### Settings (`/api/v1/settings`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/cloudflare` | List saved Cloudflare configs |
| POST | `/cloudflare` | Add Cloudflare config. Body: `{label?, cf_email, cf_api_key, is_default?}` |
| DELETE | `/cloudflare/{config_id}` | Delete a Cloudflare config |
| GET | `/alerts` | Get alert settings (webhook_url, intervals) |
| PUT | `/alerts` | Update alert settings |

### TOTP Vault (`/api/v1/totp`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all tenants with MFA secrets + live 6-digit TOTP codes |
| GET | `/{tenant_id}` | Get TOTP code for one tenant |
| PUT | `/{tenant_id}/secret` | Set/update MFA secret. Body: `{secret: "BASE32..."}` |
| DELETE | `/{tenant_id}/secret` | Remove MFA secret from tenant |

### WebSocket (`/ws/live`)
Real-time event stream. Auth via `token` query param or `session_token` cookie.

Event types:
```json
{"type": "tenant_setup_progress", "tenant_id": "...", "step": 3, "total": 12, "message": "Creating app registration...", "status": "running"}
{"type": "mailbox_pipeline_progress", "job_id": "...", "step": 5, "total": 9, "message": "Setting up DKIM...", "status": "running"}
{"type": "alert", "tenant_id": "...", "alert_type": "smtp_blocked", "severity": "critical", "message": "..."}
```

---

## Celery Tasks

Configured in `backend/app/tasks/celery_app.py`. Redis broker.

### Queue Routing
| Queue | Task Pattern |
|-------|-------------|
| `tenant_setup` | `app.tasks.tenant_setup.*` |
| `mailbox` | `app.tasks.mailbox_pipeline.*` |
| `monitor` | `app.tasks.monitor.*` |
| `default` | Everything else |

### Beat Schedule (Periodic Tasks)
| Name | Task | Interval |
|------|------|----------|
| `monitor-smtp-every-30m` | `run_smtp_checks` | Every 30 minutes |
| `monitor-dns-every-6h` | `run_dns_checks` | Every 6 hours |
| `reap-stale-tasks-every-5m` | `reap_stale_tasks` | Every 5 minutes |

### Tenant Setup Task — 12 Steps
Task: `app.tasks.tenant_setup.run_tenant_setup(tenant_id)`
Queue: `tenant_setup` | `acks_late=True, reject_on_worker_lost=True`

| Step | Description | Module |
|------|-------------|--------|
| 1 | Browser Login (az login + device code + MFA) | `mfa_handler.py` |
| 2 | Security Setup (MFA policy, CAP) | `security_settings.py` |
| 3 | Create App Registration | `app_registration.py` |
| 4 | Create Service Principal | `app_registration.py` |
| 5 | Create Client Secret | `app_registration.py` |
| 6 | Generate & Upload Certificate | `cert_generator.py` + `app_registration.py` |
| 7 | Add API Permissions (Graph + Exchange) | `app_registration.py` |
| 8 | Grant Admin Consent | `app_registration.py` |
| 9 | Assign Exchange Admin Role | `app_registration.py` |
| 10 | Save Credentials | writes to DB |
| 11 | Finalize | status update |
| 12 | Delete MFA Authenticator | `mfa_handler.py` |

The MFA secret (TOTP) is saved to the database as soon as it's enrolled in step 1, so even if later steps fail, the tenant's MFA code is available in the TOTP Vault for recovery.

### Mailbox Pipeline Task — 9 Steps
Task: `app.tasks.mailbox_pipeline.run_mailbox_pipeline(job_id)`
Queue: `mailbox` | `acks_late=True, reject_on_worker_lost=True`

| Step | Description | Tool Used |
|------|-------------|-----------|
| 1 | Assign License | Graph API |
| 2 | Enable Org-wide SMTP | PowerShell |
| 3 | Add Domain | Graph API |
| 4 | Verify Domain | Graph API + Cloudflare DNS |
| 5 | Setup DKIM | PowerShell + Cloudflare DNS |
| 6 | Setup DMARC | Cloudflare DNS |
| 7 | Create Mailboxes | PowerShell (batch of 10) |
| 8 | Enable SMTP per mailbox | PowerShell |
| 9 | Disable Calendar Processing | PowerShell |

### Monitor Tasks
- `run_smtp_checks()`: For each completed tenant, samples up to 5 mailboxes, tests SMTP AUTH on `smtp.office365.com:587`
- `run_dns_checks()`: Validates MX, SPF, DKIM, DMARC records via `dig`
- `reap_stale_tasks()`: Marks tenants stuck `running`/`queued` >15min as `failed`, mailbox jobs >30min as `failed`

---

## Key Services

### Encryption (`backend/app/services/encryption.py`)
All sensitive data (passwords, API keys, certificates) is encrypted at rest using Fernet symmetric encryption. The `FERNET_KEY` env var must be set.

```python
encrypt(plaintext: str) -> bytes      # Encrypt string
decrypt(ciphertext: bytes) -> str     # Decrypt to string
encrypt_bytes(data: bytes) -> bytes   # Encrypt raw bytes
decrypt_bytes(data: bytes) -> bytes   # Decrypt raw bytes
```

### Graph Client (`backend/app/services/graph_client.py`)
Microsoft Graph API client using OAuth2 client credentials flow. Features:
- Token caching with automatic refresh
- Retry with exponential backoff for 429/5xx
- Beta endpoint support (`use_beta=True`)

### Cloudflare Client (`backend/app/services/cloudflare_client.py`)
DNS record management: create, upsert, delete CNAME/MX/TXT records for domain verification, DKIM, DMARC.

### PowerShell Runner (`backend/app/services/powershell.py`)
Executes Exchange Online commands via `pwsh` subprocess with certificate-based auth. Features:
- `escape_ps_string()` prevents command injection in single-quoted strings
- Batched execution with configurable batch size and timeout
- Parses output lines for CREATED/EXISTS/FAILED status

### Name Generator (`backend/app/services/name_generator.py`)
Generates random but realistic mailbox identities: `{email, display_name, alias, password}`.

---

## Selenium Worker Details

Located in `backend/app/selenium_worker/`. Requires Chrome + ChromeDriver + Xvfb on the host.

### MFA Handler (`mfa_handler.py`)
The most complex module. Handles:
1. **Azure CLI device code flow**: Opens `https://login.microsoftonline.com/common/oauth2/deviceauth` in Selenium
2. **Password entry**: Enters admin credentials
3. **MFA enrollment**: If Microsoft forces MFA setup, navigates the authenticator enrollment wizard, extracts the TOTP secret from the QR code page
4. **TOTP generation**: Uses `pyotp` to generate 6-digit codes for MFA challenges
5. **Password change**: Handles forced password change on first login
6. **Token acquisition**: Gets Graph API token via `az account get-access-token`

**Important**: The device login URL `microsoft.com/devicelogin` returns HTTP 403 from datacenter IPs. Use `login.microsoftonline.com/common/oauth2/deviceauth` instead.

### App Registration (`app_registration.py`)
All Graph API calls for Azure AD setup:
- Create app registration with required resource access
- Create service principal
- Generate client secret (2-year validity)
- Generate and upload X.509 certificate
- Add permissions: Microsoft Graph (Mail, User, Directory) + Exchange (full_access_as_app)
- Grant admin consent
- Assign Exchange Administrator directory role

### Certificate Generator (`cert_generator.py`)
Generates self-signed X.509 certificates for Exchange Online certificate-based auth:
- 2048-bit RSA key
- 2-year validity
- Returns PEM (for upload) and PFX (for PowerShell auth) with random password

---

## Frontend Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Redirect | Server-side redirect to `/tenants` |
| `/login` | Login | Password-only login form |
| `/tenants` | Tenant List | Main dashboard. Filter by status, start setup, retry, delete, download credentials |
| `/tenants/new` | New Tenant | Create single tenant form |
| `/mailboxes` | All Mailboxes | Paginated list of all mailboxes across tenants |
| `/mailboxes/[tenantId]` | Tenant Mailboxes | Mailboxes for one tenant + create mailbox job |
| `/monitor` | Health Dashboard | Summary stats, alert list, tenant health overview |
| `/monitor/[tenantId]` | Tenant Health | Health check history for one tenant |
| `/settings` | Settings | Cloudflare API configs, alert webhook settings |
| `/totp` | TOTP Vault | Live 6-digit TOTP codes for all enrolled tenants. Circular countdown timers. Add/remove secrets manually |

### Auth Flow
- `useAuth` hook calls `GET /api/v1/auth/verify` on mount
- If 401, redirects to `/login` via `window.location.href`
- `AuthGuard` component wraps all authenticated pages, shows spinner during check

### WebSocket
- `useWebSocket` hook connects to `/ws/live` with session token
- Receives real-time progress events for setup/mailbox tasks
- Components use these events to update progress bars and status badges

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Description |
|----------|-------------|
| `DASHBOARD_PASSWORD` | Password for dashboard login |
| `FERNET_KEY` | Encryption key. Generate: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DATABASE_URL` | PostgreSQL async URL: `postgresql+asyncpg://user:pass@host:5432/db` |
| `DATABASE_URL_SYNC` | PostgreSQL sync URL: `postgresql://user:pass@host:5432/db` |
| `DB_PASSWORD` | PostgreSQL user password (used by deploy.sh) |
| `REDIS_URL` | Redis URL: `redis://:password@host:6379/0` |
| `REDIS_PASSWORD` | Redis password (used by deploy.sh) |
| `CORS_ORIGINS` | JSON array of allowed origins |

---

## Deployment

### Prerequisites (on Ubuntu server)
- Python 3.11+
- Node.js 20+
- PostgreSQL 16
- Redis 7
- Caddy 2
- Google Chrome + ChromeDriver
- Xvfb (headless display)
- PowerShell 7 (`pwsh`) + Exchange Online module
- Azure CLI (`az`)

### Quick Deploy
```bash
# First time (installs system packages, sets up DB + Redis):
sudo ./deploy.sh --init

# Subsequent deploys:
sudo ./deploy.sh
```

The deploy script:
1. Creates Python venv and installs backend dependencies
2. Runs Alembic migrations
3. Builds Next.js frontend (standalone mode)
4. Installs systemd services
5. Starts/restarts all services

### Systemd Services
| Service | Command | Port |
|---------|---------|------|
| `tenant-api` | `uvicorn app.main:app --host 127.0.0.1 --port 8000` | 8000 |
| `tenant-celery` | `celery -A app.tasks.celery_app worker -Q default,mailbox,monitor -c 4` | — |
| `tenant-beat` | `celery -A app.tasks.celery_app beat` | — |
| `tenant-frontend` | `node .next/standalone/server.js` | 3000 |
| `caddy` | Reverse proxy (auto HTTPS) | 80, 443 |

**Note**: The tenant_setup queue is handled by a separate Selenium worker (not the main celery worker) because it requires Chrome + Xvfb.

### Next.js Standalone Build
Next.js is configured with `output: "standalone"`. After `npm run build`, you must copy static assets:
```bash
cp -r .next/static .next/standalone/.next/static
```

### Useful Commands
```bash
# View logs
journalctl -u tenant-api -f
journalctl -u tenant-celery -f
journalctl -u tenant-beat -f
journalctl -u tenant-frontend -f

# Restart services
sudo systemctl restart tenant-api tenant-celery tenant-beat tenant-frontend

# Reload Caddy config
sudo systemctl reload caddy
```

---

## Security Notes

- All sensitive data encrypted at rest (Fernet)
- Session tokens stored in Redis with TTL (72h default)
- httponly cookies for session management
- UFW firewall: only ports 22, 80, 443 open
- `.env` files chmod 600
- Redis configured with password + maxmemory 256mb (allkeys-lru)
- PowerShell strings escaped to prevent command injection
- Input validation: EmailStr, domain format, bounded pagination
- CORS restricted to configured origins
- Secrets never sent to frontend (TOTP codes computed server-side)

---

## Common Modifications Guide

### Adding a new API endpoint
1. Create or edit the router file in `backend/app/api/`
2. Register the router in `backend/app/main.py` if new file
3. Add corresponding method in `frontend/src/lib/api.ts`
4. Add TypeScript types in `frontend/src/lib/types.ts` if needed

### Adding a new Celery task
1. Create task function in `backend/app/tasks/`
2. Add queue routing in `backend/app/tasks/celery_app.py` (`task_routes` dict)
3. If periodic, add to `beat_schedule` in the same file
4. Use `acks_late=True, reject_on_worker_lost=True` for reliability

### Adding a new frontend page
1. Create `frontend/src/app/<route>/page.tsx`
2. Create `frontend/src/app/<route>/layout.tsx` with AuthGuard wrapper
3. Add navigation entry in `frontend/src/components/layout/Sidebar.tsx`

### Modifying the tenant setup flow
1. Edit steps in `backend/app/selenium_worker/setup_tenant.py`
2. Individual step logic lives in sibling files (`mfa_handler.py`, `app_registration.py`, etc.)
3. Update `total_steps` count if adding/removing steps
4. Progress is published via the callback: `progress(step_number, "message")`

### Modifying the mailbox pipeline
1. Edit `backend/app/tasks/mailbox_pipeline.py`
2. Steps use `GraphClient` for API calls and `PowerShellRunner` for Exchange commands
3. DNS changes go through `CloudflareClient`
