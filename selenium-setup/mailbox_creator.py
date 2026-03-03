"""Domain setup + Room mailbox creation via Graph API, Cloudflare, and PowerShell.

Self-contained module — no api-scripts imports. Reads credentials from
selenium-setup/output/{tenant}/credentials.json + cert.pfx.

Five phases:
  1. Add domain to tenant (Graph API) + create DNS records (Cloudflare)
  2. Verify domain (Graph API with retry/backoff)
  3. Create room mailboxes (New-Mailbox -Room via PowerShell)
  4. Enable SMTP auth (Set-CASMailbox)
  5. Configure calendar processing (Set-CalendarProcessing)
"""

import json
import os
import random
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Paths ────────────────────────────────────────────────────────────────────
_BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = _BASE_DIR / "output"
PWSH_PATH = "pwsh"

# ── API constants ────────────────────────────────────────────────────────────
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
GRAPH_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
CLOUDFLARE_API_URL = "https://api.cloudflare.com/client/v4"

DOMAIN_VERIFY_BACKOFF = [5, 15, 30, 60]  # seconds between retry attempts

# ── Name Generator ───────────────────────────────────────────────────────────
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
    "Kenneth", "Carol", "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa",
    "Timothy", "Deborah", "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy",
    "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen", "Brenda",
    "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole", "Brandon", "Helen",
    "Benjamin", "Samantha", "Samuel", "Katherine", "Raymond", "Christine", "Gregory", "Debra",
    "Frank", "Rachel", "Alexander", "Carolyn", "Patrick", "Janet", "Jack", "Catherine",
    "Dennis", "Maria", "Jerry", "Heather", "Tyler", "Diane", "Aaron", "Ruth",
    "Jose", "Julie", "Adam", "Olivia", "Nathan", "Joyce", "Henry", "Virginia",
    "Peter", "Victoria", "Zachary", "Kelly", "Douglas", "Lauren", "Harold", "Christina",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill",
    "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell",
    "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
]


def generate_mailbox_identities(count: int, domain: str, tenant_short: str) -> list[dict]:
    """Generate unique mailbox identities for room mailboxes."""
    rng = random.Random(42)
    pairs = set()
    while len(pairs) < count:
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        if (first, last) not in pairs:
            pairs.add((first, last))

    identities = []
    for i, (first, last) in enumerate(sorted(pairs), start=1):
        alias = f"{first.lower()}.{last.lower()}"
        identities.append({
            "first_name": first,
            "last_name": last,
            "display_name": f"{first} {last}",
            "alias": alias,
            "email": f"{alias}@{domain}",
            "password": f"{tenant_short}@Iced#{i:04d}",
        })
    return identities


# ── Graph API Client (inline) ───────────────────────────────────────────────

class _GraphClient:
    """Minimal Microsoft Graph API client using client_credentials flow."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.token_url = TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._token_expiry = 0

    def _acquire_token(self):
        resp = requests.post(self.token_url, data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": GRAPH_SCOPE,
        }, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Token request failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 300

    def _headers(self) -> dict:
        if not self._token or time.time() >= self._token_expiry:
            self._acquire_token()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def get(self, path: str) -> requests.Response:
        resp = requests.get(f"{GRAPH_URL}{path}", headers=self._headers(), timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph GET {path} → {resp.status_code}: {resp.text}")
        return resp

    def post(self, path: str, json_data: dict = None) -> requests.Response:
        resp = requests.post(f"{GRAPH_URL}{path}", headers=self._headers(), json=json_data, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph POST {path} → {resp.status_code}: {resp.text}")
        return resp

    def patch(self, path: str, json_data: dict = None, api_version: str = "v1.0") -> requests.Response:
        url = f"https://graph.microsoft.com/{api_version}/{path}"
        resp = requests.patch(url, headers=self._headers(), json=json_data, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph PATCH {path} → {resp.status_code}: {resp.text}")
        return resp


# ── Cloudflare Client (inline) ──────────────────────────────────────────────

class _CloudflareClient:
    """Minimal Cloudflare DNS API client using Global API Key auth."""

    def __init__(self, email: str, api_key: str):
        self.email = email
        self.api_key = api_key
        self._zone_cache = {}

    def _headers(self) -> dict:
        return {"X-Auth-Key": self.api_key, "X-Auth-Email": self.email, "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = requests.request(method, f"{CLOUDFLARE_API_URL}{path}", headers=self._headers(), timeout=30, **kwargs)
        data = resp.json()
        if not data.get("success", False):
            raise RuntimeError(f"Cloudflare {method} {path} failed: {data.get('errors', [])}")
        return data

    def get_zone_id(self, domain: str) -> str:
        if domain in self._zone_cache:
            return self._zone_cache[domain]
        data = self._request("GET", f"/zones?name={domain}")
        results = data.get("result", [])
        if not results:
            raise RuntimeError(f"Zone not found for domain: {domain}")
        zone_id = results[0]["id"]
        self._zone_cache[domain] = zone_id
        return zone_id

    def list_dns_records(self, domain: str, type: str = None, name: str = None) -> list:
        zone_id = self.get_zone_id(domain)
        params = {}
        if type:
            params["type"] = type
        if name:
            params["name"] = name
        data = self._request("GET", f"/zones/{zone_id}/dns_records", params=params)
        return data.get("result", [])

    def create_dns_record(self, domain: str, record_type: str, name: str,
                          content: str, ttl: int = 3600, priority: int = None,
                          proxied: bool = False) -> dict:
        zone_id = self.get_zone_id(domain)
        payload = {"type": record_type, "name": name, "content": content, "ttl": ttl, "proxied": proxied}
        if priority is not None:
            payload["priority"] = priority
        data = self._request("POST", f"/zones/{zone_id}/dns_records", json=payload)
        return data.get("result", {})

    def upsert_dns_record(self, domain: str, record_type: str, name: str,
                          content: str, ttl: int = 3600, priority: int = None,
                          proxied: bool = False) -> dict:
        existing = self.list_dns_records(domain, type=record_type, name=name)
        zone_id = self.get_zone_id(domain)
        payload = {"type": record_type, "name": name, "content": content, "ttl": ttl, "proxied": proxied}
        if priority is not None:
            payload["priority"] = priority
        if existing:
            record_id = existing[0]["id"]
            data = self._request("PUT", f"/zones/{zone_id}/dns_records/{record_id}", json=payload)
        else:
            data = self._request("POST", f"/zones/{zone_id}/dns_records", json=payload)
        return data.get("result", {})


# ── Credential Loader ────────────────────────────────────────────────────────

def _resolve_org_domain(tenant_id: str, client_id: str, client_secret: str) -> str | None:
    """Query Graph API to get the initial .onmicrosoft.com domain."""
    try:
        token_url = TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
        resp = requests.post(token_url, data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": GRAPH_SCOPE,
        }, timeout=30)
        if resp.status_code != 200:
            return None
        token = resp.json()["access_token"]
        resp = requests.get(
            f"{GRAPH_URL}/organization?$select=verifiedDomains",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        for org in resp.json().get("value", []):
            for d in org.get("verifiedDomains", []):
                if d.get("isInitial") and d["name"].endswith(".onmicrosoft.com"):
                    return d["name"]
    except Exception:
        pass
    return None


def load_tenant_credentials(tenant_name: str) -> dict:
    """Load tenant credentials from output/{tenant_name}/credentials.json."""
    creds_path = OUTPUT_DIR / tenant_name / "credentials.json"
    if not creds_path.exists():
        raise FileNotFoundError(f"Credentials not found: {creds_path}")

    with open(creds_path) as f:
        data = json.load(f)

    required = ["tenant_id", "client_id", "client_secret", "cert_password"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Missing keys in {creds_path}: {', '.join(missing)}")

    data["tenant_name"] = tenant_name

    # Resolve org domain via Graph API
    real_org = _resolve_org_domain(data["tenant_id"], data["client_id"], data["client_secret"])
    data["org_domain"] = real_org or f"{tenant_name}.onmicrosoft.com"

    # Cert PFX path
    pfx_path = OUTPUT_DIR / tenant_name / "cert.pfx"
    if not pfx_path.exists():
        raise FileNotFoundError(f"Certificate not found: {pfx_path}")
    data["cert_pfx_path"] = str(pfx_path)

    return data


# ── PowerShell Runner ────────────────────────────────────────────────────────

def check_pwsh_available() -> bool:
    return shutil.which(PWSH_PATH) is not None


def ensure_exchange_module() -> None:
    result = subprocess.run(
        [PWSH_PATH, "-Command",
         "if (-not (Get-Module -ListAvailable ExchangeOnlineManagement)) { "
         "Install-Module ExchangeOnlineManagement -Force -Scope CurrentUser -AllowClobber }"],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to ensure Exchange module: {result.stderr}")


def _connect_script(tenant: dict) -> str:
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$secPwd = ConvertTo-SecureString '{tenant['cert_password']}' -AsPlainText -Force",
        f"Connect-ExchangeOnline -AppId '{tenant['client_id']}' "
        f"-CertificateFilePath '{tenant['cert_pfx_path']}' "
        f"-CertificatePassword $secPwd "
        f"-Organization '{tenant['org_domain']}' -ShowBanner:$false",
    ]
    return "\n".join(lines)


def _disconnect_script() -> str:
    return "Disconnect-ExchangeOnline -Confirm:$false"


def _run_powershell(tenant: dict, commands: list[str], timeout: int = 600) -> tuple[str, str]:
    """Run PowerShell commands wrapped in Exchange connect/disconnect."""
    full_script = "\n".join([
        _connect_script(tenant),
        *commands,
        _disconnect_script(),
    ])
    result = subprocess.run(
        [PWSH_PATH, "-Command", full_script],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PowerShell error (exit {result.returncode}):\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
    return result.stdout, result.stderr


def _run_powershell_batched(
    tenant: dict, commands: list[str], batch_size: int = 10, timeout: int = 600,
    on_batch=None,
) -> tuple[str, str]:
    """Run commands in batches with fresh Exchange connections."""
    all_stdout, all_stderr = [], []
    total_batches = (len(commands) + batch_size - 1) // batch_size
    for i in range(0, len(commands), batch_size):
        batch = commands[i:i + batch_size]
        batch_num = i // batch_size + 1
        if on_batch:
            on_batch(batch_num, total_batches)
        stdout, stderr = _run_powershell(tenant, batch, timeout=timeout)
        all_stdout.append(stdout)
        all_stderr.append(stderr)
    return "\n".join(all_stdout), "\n".join(all_stderr)


# ── Security Setup ───────────────────────────────────────────────────────────

def _disable_security_and_enable_smtp(graph: _GraphClient, progress) -> None:
    """Disable Security Defaults, MFA registration, system-preferred MFA, and enable org SMTP AUTH."""

    # 1. Disable Security Defaults
    progress("Step 0/5: Disabling Security Defaults...")
    try:
        graph.patch("policies/identitySecurityDefaultsEnforcementPolicy", {"isEnabled": False})
        progress("Step 0/5: Security Defaults disabled")
    except RuntimeError as e:
        progress(f"Step 0/5: Security Defaults — {e}")

    # 2. Disable MFA registration campaign
    progress("Step 0/5: Disabling MFA registration campaign...")
    try:
        graph.patch("policies/authenticationMethodsPolicy", {"registrationCampaign": {"state": "disabled"}})
        progress("Step 0/5: MFA registration campaign disabled")
    except RuntimeError as e:
        progress(f"Step 0/5: MFA registration campaign — {e}")

    # 3. Disable system-preferred MFA
    progress("Step 0/5: Disabling system-preferred MFA...")
    try:
        graph.patch("policies/authenticationMethodsPolicy",
                    {"systemCredentialPreferences": {"state": "disabled"}}, api_version="beta")
        progress("Step 0/5: System-preferred MFA disabled")
    except RuntimeError as e:
        progress(f"Step 0/5: System-preferred MFA — {e}")

    # 4. Enable SMTP AUTH org-wide
    progress("Step 0/5: Enabling org-wide SMTP AUTH...")
    try:
        graph.patch("admin/exchange/transportConfig",
                    {"smtpClientAuthenticationDisabled": False}, api_version="beta")
        progress("Step 0/5: Org-wide SMTP AUTH enabled")
    except RuntimeError as e:
        progress(f"Step 0/5: Org SMTP AUTH — {e}")


# ── Domain Setup ─────────────────────────────────────────────────────────────

def _add_domain_and_dns(graph: _GraphClient, cf: _CloudflareClient, domain: str, progress) -> None:
    """Phase 1: Add domain to tenant via Graph + create DNS records in Cloudflare."""
    progress("Step 1/5: Adding domain to tenant...")

    # 1. Add domain to tenant
    try:
        graph.post("/domains", {"id": domain})
        progress("Step 1/5: Domain added to tenant")
    except RuntimeError as e:
        if "already exist" in str(e).lower() or "409" in str(e):
            progress("Step 1/5: Domain already exists in tenant")
        else:
            raise

    # 2. Fetch verification DNS records (retry — may take a moment)
    verification_records = []
    for attempt in range(1, 6):
        progress(f"Step 1/5: Fetching verification records (attempt {attempt})")
        try:
            resp = graph.get(f"/domains/{domain}/verificationDnsRecords")
            verification_records = resp.json().get("value", [])
            break
        except RuntimeError as e:
            if ("404" in str(e) or "ResourceNotFound" in str(e)) and attempt < 5:
                time.sleep(attempt * 5)
            else:
                raise

    # 3. Create TXT verification record in Cloudflare
    for rec in verification_records:
        if rec.get("recordType", "") == "Txt":
            txt_value = rec.get("text", "")
            progress(f"Step 1/5: Creating TXT verification record")
            cf.upsert_dns_record(domain, "TXT", domain, txt_value, proxied=False)

    # 4. Create MX record
    mx_host = domain.replace(".", "-") + ".mail.protection.outlook.com"
    progress(f"Step 1/5: Creating MX record → {mx_host}")
    cf.upsert_dns_record(domain, "MX", domain, mx_host, priority=0, proxied=False)

    # 5. Create SPF TXT record
    spf_value = "v=spf1 include:spf.protection.outlook.com -all"
    progress("Step 1/5: Creating SPF record")
    try:
        cf.create_dns_record(domain, "TXT", domain, spf_value, proxied=False)
    except RuntimeError as e:
        if "already been taken" in str(e).lower() or "81057" in str(e):
            existing = cf.list_dns_records(domain, type="TXT", name=domain)
            spf_exists = any("spf" in r.get("content", "").lower() for r in existing)
            if not spf_exists:
                cf.create_dns_record(domain, "TXT", domain, spf_value, proxied=False)
        else:
            raise

    # 6. Create autodiscover CNAME
    progress("Step 1/5: Creating autodiscover CNAME")
    cf.upsert_dns_record(domain, "CNAME", f"autodiscover.{domain}",
                         "autodiscover.outlook.com", proxied=False)

    progress("Step 1/5: Done — domain added, DNS records created")


def _verify_domain(graph: _GraphClient, domain: str, progress) -> None:
    """Phase 2: Verify domain in Microsoft 365 with retry + backoff."""
    progress("Step 2/5: Verifying domain...")

    # Check if already verified
    try:
        resp = graph.get(f"/domains/{domain}")
        if resp.json().get("isVerified", False):
            progress("Step 2/5: Domain already verified")
            return
    except RuntimeError:
        pass

    # Attempt verification with retries
    for attempt, wait in enumerate(DOMAIN_VERIFY_BACKOFF, start=1):
        progress(f"Step 2/5: Verification attempt {attempt}/{len(DOMAIN_VERIFY_BACKOFF)}")
        try:
            resp = graph.post(f"/domains/{domain}/verify")
            if resp.json().get("isVerified", False):
                progress("Step 2/5: Domain verified successfully")
                return
        except RuntimeError:
            pass

        if attempt < len(DOMAIN_VERIFY_BACKOFF):
            progress(f"Step 2/5: Waiting {wait}s for DNS propagation...")
            time.sleep(wait)

    # Final attempt
    progress("Step 2/5: Final verification attempt")
    try:
        resp = graph.post(f"/domains/{domain}/verify")
        if resp.json().get("isVerified", False):
            progress("Step 2/5: Domain verified successfully")
            return
    except RuntimeError as e:
        raise RuntimeError(f"Domain '{domain}' verification failed after all attempts: {e}")

    raise RuntimeError(f"Domain '{domain}' could not be verified after all attempts")


# ── Main Function ────────────────────────────────────────────────────────────

def create_room_mailboxes(
    tenant_name: str,
    domain: str,
    count: int = 50,
    cf_email: str = "",
    cf_api_key: str = "",
    on_progress=None,
) -> dict:
    """Domain setup + room mailbox creation for a tenant.

    Args:
        tenant_name: folder name under output/ (e.g. "UmberIbisMeadow")
        domain: custom email domain (e.g. "forachieve.info")
        count: number of room mailboxes to create
        cf_email: Cloudflare account email
        cf_api_key: Cloudflare Global API Key
        on_progress: optional callback(step_text) for live progress updates

    Returns:
        dict with status and result counts
    """
    def progress(text):
        print(f"[mailbox] {tenant_name}: {text}")
        if on_progress:
            on_progress(text)

    progress("Loading credentials...")

    # Load credentials
    tenant = load_tenant_credentials(tenant_name)

    # Check PowerShell
    if not check_pwsh_available():
        raise RuntimeError("PowerShell (pwsh) not available on PATH")

    progress("Ensuring Exchange module is installed...")
    ensure_exchange_module()

    # ── Phase 0: Security setup (disable MFA, enable org SMTP) ─────────
    graph = _GraphClient(tenant["tenant_id"], tenant["client_id"], tenant["client_secret"])
    _disable_security_and_enable_smtp(graph, progress)

    # ── Phase 1 & 2: Domain setup ────────────────────────────────────────
    if cf_email and cf_api_key:
        cf = _CloudflareClient(email=cf_email, api_key=cf_api_key)
        _add_domain_and_dns(graph, cf, domain, progress)
        _verify_domain(graph, domain, progress)
        # Wait for Exchange Online to propagate the verified domain
        progress("Waiting 60s for Exchange to recognize domain...")
        time.sleep(60)
    else:
        progress("Step 1/5: Skipped (no Cloudflare credentials)")
        progress("Step 2/5: Skipped (no Cloudflare credentials)")

    # ── Phase 3: Create mailboxes ────────────────────────────────────────
    identities = generate_mailbox_identities(count, domain, tenant_name)
    progress(f"Generated {len(identities)} mailbox identities")
    progress(f"Step 3/5: Creating mailboxes (0/{count})")

    create_commands = []
    for mb in identities:
        safe_pwd = mb["password"].replace("'", "''")
        create_commands.append(
            f"$pwd = ConvertTo-SecureString '{safe_pwd}' -AsPlainText -Force; "
            f"try {{ "
            f"New-Mailbox -Room -Name '{mb['display_name']}' "
            f"-Alias '{mb['alias']}' "
            f"-PrimarySmtpAddress '{mb['email']}' "
            f"-EnableRoomMailboxAccount $true "
            f"-MicrosoftOnlineServicesID '{mb['email']}' "
            f"-RoomMailboxPassword $pwd; "
            f"Write-Host 'CREATED: {mb['email']}' "
            f"}} catch {{ "
            f"if ($_.Exception.Message -like '*already exists*' -or "
            f"$_.Exception.Message -like '*proxy address*already being used*') {{ "
            f"Write-Host 'EXISTS: {mb['email']}' "
            f"}} else {{ "
            f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
            f"}} }}"
        )

    def on_create_batch(batch_num, total):
        progress(f"Step 3/5: Creating mailboxes (batch {batch_num}/{total})")

    stdout, stderr = _run_powershell_batched(
        tenant, create_commands, batch_size=10, timeout=600,
        on_batch=on_create_batch,
    )

    created, existed, create_failed = [], [], []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("CREATED:"):
            created.append(line.split("CREATED:")[1].strip())
        elif line.startswith("EXISTS:"):
            existed.append(line.split("EXISTS:")[1].strip())
        elif line.startswith("FAILED:"):
            create_failed.append(line.split("FAILED:")[1].strip())

    progress(f"Step 3/5: Done — {len(created)} created, {len(existed)} existed, {len(create_failed)} failed")

    # ── Phase 4: Enable SMTP ─────────────────────────────────────────────
    progress(f"Step 4/5: Enabling SMTP (0/{count})")

    smtp_commands = []
    for mb in identities:
        smtp_commands.append(
            f"try {{ "
            f"Set-CASMailbox -Identity '{mb['email']}' -SmtpClientAuthenticationDisabled $false; "
            f"Write-Host 'ENABLED: {mb['email']}' "
            f"}} catch {{ "
            f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
            f"}}"
        )

    def on_smtp_batch(batch_num, total):
        progress(f"Step 4/5: Enabling SMTP (batch {batch_num}/{total})")

    stdout, stderr = _run_powershell_batched(
        tenant, smtp_commands, batch_size=10, timeout=600,
        on_batch=on_smtp_batch,
    )

    smtp_enabled, smtp_failed = [], []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("ENABLED:"):
            smtp_enabled.append(line.split("ENABLED:")[1].strip())
        elif line.startswith("FAILED:"):
            smtp_failed.append(line.split("FAILED:")[1].strip())

    progress(f"Step 4/5: Done — {len(smtp_enabled)} SMTP enabled, {len(smtp_failed)} failed")

    # ── Phase 5: Configure calendars ─────────────────────────────────────
    progress(f"Step 5/5: Configuring calendars (0/{count})")

    cal_commands = []
    for mb in identities:
        cal_commands.append(
            f"try {{ "
            f"Set-CalendarProcessing -Identity '{mb['email']}' "
            f"-AutomateProcessing None "
            f"-DeleteComments $false "
            f"-DeleteSubject $false; "
            f"Write-Host 'CONFIGURED: {mb['email']}' "
            f"}} catch {{ "
            f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
            f"}}"
        )

    def on_cal_batch(batch_num, total):
        progress(f"Step 5/5: Configuring calendars (batch {batch_num}/{total})")

    stdout, stderr = _run_powershell_batched(
        tenant, cal_commands, batch_size=10, timeout=600,
        on_batch=on_cal_batch,
    )

    cal_configured, cal_failed = [], []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("CONFIGURED:"):
            cal_configured.append(line.split("CONFIGURED:")[1].strip())
        elif line.startswith("FAILED:"):
            cal_failed.append(line.split("FAILED:")[1].strip())

    progress(f"Step 5/5: Done — {len(cal_configured)} calendars configured, {len(cal_failed)} failed")

    # ── Save results ─────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_json = OUTPUT_DIR / f"{tenant_name}_mailboxes.json"
    output_data = {
        "tenant": tenant_name,
        "domain": domain,
        "count": count,
        "identities": identities,
        "results": {
            "created": created,
            "existed": existed,
            "create_failed": create_failed,
            "smtp_enabled": smtp_enabled,
            "smtp_failed": smtp_failed,
            "cal_configured": cal_configured,
            "cal_failed": cal_failed,
        },
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(output_json, "w") as f:
        json.dump(output_data, f, indent=2)

    output_csv = OUTPUT_DIR / f"{tenant_name}_mailboxes.csv"
    with open(output_csv, "w") as f:
        f.write("first_name,last_name,display_name,email,password\n")
        for mb in identities:
            f.write(f"{mb['first_name']},{mb['last_name']},{mb['display_name']},{mb['email']},{mb['password']}\n")

    total_failed = len(create_failed)
    summary = f"complete ({len(created)} created, {len(existed)} existed, {total_failed} failed)"
    progress(summary)

    return {
        "status": "complete",
        "summary": summary,
        "identities": identities,
        "created": len(created),
        "existed": len(existed),
        "failed": total_failed,
        "smtp_enabled": len(smtp_enabled),
        "smtp_failed": len(smtp_failed),
        "cal_configured": len(cal_configured),
        "cal_failed": len(cal_failed),
        "output_json": str(output_json),
        "output_csv": str(output_csv),
    }
