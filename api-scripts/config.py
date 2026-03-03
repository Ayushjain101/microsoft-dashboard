import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
SELENIUM_OUTPUT = BASE_DIR.parent / "selenium-setup" / "output"
API_OUTPUT = BASE_DIR / "output"

# ── Microsoft Graph ────────────────────────────────────────────────────
GRAPH_URL = "https://graph.microsoft.com/v1.0"
GRAPH_BETA_URL = "https://graph.microsoft.com/beta"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

# ── Cloudflare ─────────────────────────────────────────────────────────
CLOUDFLARE_API_URL = "https://api.cloudflare.com/client/v4"
CLOUDFLARE_API_KEY = os.environ.get("CLOUDFLARE_API_KEY", "0e2bd142613c0317cbdaac90dc273cd61623c")
CLOUDFLARE_EMAIL = os.environ.get("CLOUDFLARE_EMAIL", "a20@dfy1cf.com")

# ── PowerShell ─────────────────────────────────────────────────────────
PWSH_PATH = "pwsh"

# ── Mailbox defaults ──────────────────────────────────────────────────
MAILBOX_COUNT = 50
PASSWORD_TEMPLATE = "{tenant_short}@Iced#{number:04d}"

# ── Google Sheets ─────────────────────────────────────────────────────
GOOGLE_SHEET_ID = "1GKktibrC8gKYZQawPs_Cz9QWWad0Po8rkMVF9J_eP84"
PIPELINE_SHEET_NAME = "Pipeline"
