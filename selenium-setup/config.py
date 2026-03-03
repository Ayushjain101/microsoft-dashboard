"""Constants and settings for Selenium tenant setup."""

# ── Google Sheets ──────────────────────────────────────────────────────────────
GOOGLE_SHEET_ID = "15Acf8eoUirAyNGs-i-Nxx2DTigOzRbod882ma16JeO8"
SHEET_NAME = "Settings"
MAILBOX_SHEET_NAME = "Mailboxes"

# ── Resource App IDs (well-known, same in all tenants) ─────────────────────────
MICROSOFT_GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
OFFICE365_EXCHANGE_APP_ID = "00000002-0000-0ff1-ce00-000000000000"

# ── Required Graph API Application Permissions (looked up dynamically by name) ─
REQUIRED_GRAPH_PERMISSIONS = [
    "User.ReadWrite.All",
    "Directory.ReadWrite.All",
    "Application.ReadWrite.All",
    "Domain.ReadWrite.All",
    "Organization.ReadWrite.All",
    "Policy.ReadWrite.ConditionalAccess",
    "Policy.ReadWrite.AuthenticationMethod",
    "Policy.ReadWrite.SecurityDefaults",
    "Policy.Read.All",
    "UserAuthenticationMethod.ReadWrite.All",
    "Mail.ReadWrite",
    "Mail.Send",
]

# Required Graph Delegated permissions
REQUIRED_GRAPH_DELEGATED = [
    "SMTP.Send",
]

# Required Exchange Online Application Permissions
REQUIRED_EXCHANGE_PERMISSIONS = [
    "full_access_as_app",
    "Exchange.ManageAsApp",
]

# ── Role Template IDs ──────────────────────────────────────────────────────────
EXCHANGE_ADMIN_ROLE_ID = "29232cdf-9323-42fd-ade2-1d097af3e4de"

# ── URLs ───────────────────────────────────────────────────────────────────────
GRAPH_URL = "https://graph.microsoft.com/v1.0"

# ── Browser Settings ──────────────────────────────────────────────────────────
DEFAULT_WAIT_TIMEOUT = 60

# ── Server Settings ──────────────────────────────────────────────────────────
import os
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8000"))
API_KEY = os.environ.get("API_KEY", "changeme")
