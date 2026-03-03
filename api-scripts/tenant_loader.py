import json
import requests
from pathlib import Path
from config import SELENIUM_OUTPUT, TOKEN_URL_TEMPLATE, GRAPH_URL, GRAPH_SCOPE

REQUIRED_KEYS = ["admin_email", "admin_password", "tenant_id", "client_id",
                 "client_secret", "cert_base64", "cert_password"]


def _resolve_org_domain(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Query Graph API to get the actual initial .onmicrosoft.com domain."""
    token_url = TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
    resp = requests.post(token_url, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": GRAPH_SCOPE,
    })
    if resp.status_code != 200:
        return None
    token = resp.json()["access_token"]
    resp = requests.get(
        f"{GRAPH_URL}/organization?$select=verifiedDomains",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        return None
    for org in resp.json().get("value", []):
        for d in org.get("verifiedDomains", []):
            if d.get("isInitial") and d["name"].endswith(".onmicrosoft.com"):
                return d["name"]
    return None


def load_tenant(identifier: str) -> dict:
    """Load tenant credentials from selenium-setup/output/.

    Args:
        identifier: tenant name (e.g. MoonstoneDarterInlet) or
                    admin email (e.g. admin@MoonstoneDarterInlet.onmicrosoft.com)
    """
    # Normalise: extract tenant name from email if needed
    if "@" in identifier:
        tenant_name = identifier.split("@")[1].split(".")[0]
    else:
        tenant_name = identifier

    json_path = SELENIUM_OUTPUT / f"{tenant_name}.json"
    if not json_path.exists():
        raise FileNotFoundError(f"Tenant file not found: {json_path}")

    with open(json_path) as f:
        data = json.load(f)

    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"Missing keys in {json_path.name}: {', '.join(missing)}")

    # Derived fields
    data["tenant_name"] = tenant_name

    # Resolve actual org domain from Graph (handles credential mismatch)
    real_org = _resolve_org_domain(data["tenant_id"], data["client_id"], data["client_secret"])
    data["org_domain"] = real_org or f"{tenant_name}.onmicrosoft.com"

    # Cert PFX path — check subdirectory first, then root
    pfx_path = SELENIUM_OUTPUT / tenant_name / "cert.pfx"
    if not pfx_path.exists():
        pfx_path = SELENIUM_OUTPUT / f"{tenant_name}.pfx"
    data["cert_pfx_path"] = str(pfx_path) if pfx_path.exists() else None

    return data
