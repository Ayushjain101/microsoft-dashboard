"""App Registration, permissions, admin consent, and role assignment via Graph API.

Token comes from `az account get-access-token` (delegated admin token).
Permissions are looked up dynamically by name from the service principal's appRoles.
"""

import time
from datetime import datetime

import requests

from config import (
    EXCHANGE_ADMIN_ROLE_ID,
    GRAPH_URL,
    MICROSOFT_GRAPH_APP_ID,
    OFFICE365_EXCHANGE_APP_ID,
    REQUIRED_EXCHANGE_PERMISSIONS,
    REQUIRED_GRAPH_DELEGATED,
    REQUIRED_GRAPH_PERMISSIONS,
)


def _ts():
    return datetime.now().strftime("%H:%M:%S")

def info(msg):  print(f"[{_ts()}] INFO   {msg}")
def ok(msg):    print(f"[{_ts()}] OK     {msg}")
def warn(msg):  print(f"[{_ts()}] WARN   {msg}")


# ── Generic API helpers ────────────────────────────────────────────────────────

def api_get(token, url):
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} → {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def api_post(token, url, body):
    resp = requests.post(url, json=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    if resp.status_code >= 400:
        raise RuntimeError(f"POST {url} → {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.text else {}


def api_patch(token, url, body):
    resp = requests.patch(url, json=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    if resp.status_code >= 400:
        raise RuntimeError(f"PATCH {url} → {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.text else {}


# ── Permission Lookup ──────────────────────────────────────────────────────────

def lookup_sp_roles(token, app_id):
    """Find a service principal by appId and return its id + appRoles + scopes."""
    data = api_get(token,
        f"{GRAPH_URL}/servicePrincipals?$filter=appId eq '{app_id}'"
        f"&$select=id,appId,appRoles,oauth2PermissionScopes"
    )
    if not data.get("value"):
        raise RuntimeError(f"Service principal not found for appId {app_id}")
    sp = data["value"][0]
    roles = {r["value"]: r["id"] for r in sp.get("appRoles", [])}
    scopes = {s["value"]: s["id"] for s in sp.get("oauth2PermissionScopes", [])}
    return sp["id"], roles, scopes


# ── Steps ──────────────────────────────────────────────────────────────────────

def step_create_app(token, app_name):
    """Create App Registration via Graph API. Returns (object_id, client_id)."""
    info(f"Creating App Registration: '{app_name}' ...")
    result = api_post(token, f"{GRAPH_URL}/applications", {
        "displayName": app_name,
        "signInAudience": "AzureADMyOrg",
    })
    app_object_id = result["id"]
    client_id = result["appId"]
    ok(f"App created — Client ID: {client_id}, Object ID: {app_object_id}")
    return app_object_id, client_id


def step_create_secret(token, app_object_id):
    """Create client secret. Returns the secret text."""
    info("Creating client secret ...")
    result = api_post(token, f"{GRAPH_URL}/applications/{app_object_id}/addPassword", {
        "passwordCredential": {
            "displayName": "AutoSetupSecret",
            "endDateTime": "2028-12-31T23:59:59Z",
        }
    })
    secret = result["secretText"]
    ok("Client secret created (expires 2028-12-31)")
    return secret


def step_create_service_principal(token, client_id):
    """Create (or get existing) service principal. Returns sp_id."""
    info("Creating service principal ...")
    try:
        result = api_post(token, f"{GRAPH_URL}/servicePrincipals", {
            "appId": client_id,
        })
        sp_id = result["id"]
        ok(f"Service principal created: {sp_id}")
        return sp_id
    except RuntimeError as e:
        err_lower = str(e).lower()
        if "already exists" in err_lower or "already in use" in err_lower or "409" in str(e):
            data = api_get(token,
                f"{GRAPH_URL}/servicePrincipals?$filter=appId eq '{client_id}'&$select=id"
            )
            sp_id = data["value"][0]["id"]
            ok(f"Service principal already exists: {sp_id}")
            return sp_id
        raise


def step_add_permissions(token, app_object_id):
    """Look up permission IDs dynamically and write them to the app manifest.

    Returns (graph_sp_id, graph_roles, graph_scopes, exchange_sp_id, exchange_roles).
    """
    info("Looking up permission IDs ...")

    graph_sp_id, graph_roles, graph_scopes = lookup_sp_roles(token, MICROSOFT_GRAPH_APP_ID)
    ok(f"  Graph API SP: {graph_sp_id} ({len(graph_roles)} roles, {len(graph_scopes)} scopes)")

    exchange_sp_id, exchange_roles, exchange_scopes = lookup_sp_roles(token, OFFICE365_EXCHANGE_APP_ID)
    ok(f"  Exchange SP: {exchange_sp_id} ({len(exchange_roles)} roles)")

    # Build Graph Application permissions
    graph_resource_access = []
    for perm_name in REQUIRED_GRAPH_PERMISSIONS:
        role_id = graph_roles.get(perm_name)
        if role_id:
            graph_resource_access.append({"id": role_id, "type": "Role"})
            ok(f"  + [Graph] {perm_name}")
        else:
            warn(f"  ! [Graph] {perm_name} — NOT FOUND in this tenant")

    # Graph Delegated permissions
    for perm_name in REQUIRED_GRAPH_DELEGATED:
        scope_id = graph_scopes.get(perm_name)
        if scope_id:
            graph_resource_access.append({"id": scope_id, "type": "Scope"})
            ok(f"  + [Graph] {perm_name} (Delegated)")
        else:
            warn(f"  ! [Graph] {perm_name} (Delegated) — NOT FOUND")

    # Exchange Application permissions
    exchange_resource_access = []
    for perm_name in REQUIRED_EXCHANGE_PERMISSIONS:
        role_id = exchange_roles.get(perm_name)
        if role_id:
            exchange_resource_access.append({"id": role_id, "type": "Role"})
            ok(f"  + [Exchange] {perm_name}")
        else:
            warn(f"  ! [Exchange] {perm_name} — NOT FOUND in this tenant")

    # PATCH app manifest
    required_access = []
    if graph_resource_access:
        required_access.append({
            "resourceAppId": MICROSOFT_GRAPH_APP_ID,
            "resourceAccess": graph_resource_access,
        })
    if exchange_resource_access:
        required_access.append({
            "resourceAppId": OFFICE365_EXCHANGE_APP_ID,
            "resourceAccess": exchange_resource_access,
        })

    info("Writing permissions to app manifest ...")
    api_patch(token, f"{GRAPH_URL}/applications/{app_object_id}", {
        "requiredResourceAccess": required_access,
    })
    ok("All permissions added to app manifest")

    return graph_sp_id, graph_roles, graph_scopes, exchange_sp_id, exchange_roles


def step_grant_admin_consent(token, app_sp_id,
                              graph_sp_id, graph_roles, graph_scopes,
                              exchange_sp_id, exchange_roles):
    """Grant admin consent by creating appRoleAssignment for each permission."""
    info("Granting admin consent ...")

    total = 0
    granted = 0

    # Graph Application permissions
    for perm_name in REQUIRED_GRAPH_PERMISSIONS:
        role_id = graph_roles.get(perm_name)
        if not role_id:
            continue
        total += 1
        try:
            api_post(token, f"{GRAPH_URL}/servicePrincipals/{app_sp_id}/appRoleAssignments", {
                "principalId": app_sp_id,
                "resourceId": graph_sp_id,
                "appRoleId": role_id,
            })
            ok(f"  Consented: {perm_name}")
            granted += 1
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                ok(f"  Already consented: {perm_name}")
                granted += 1
            else:
                warn(f"  Failed: {perm_name} — {str(e)[:100]}")

    # Exchange Application permissions
    for perm_name in REQUIRED_EXCHANGE_PERMISSIONS:
        role_id = exchange_roles.get(perm_name)
        if not role_id:
            continue
        total += 1
        try:
            api_post(token, f"{GRAPH_URL}/servicePrincipals/{app_sp_id}/appRoleAssignments", {
                "principalId": app_sp_id,
                "resourceId": exchange_sp_id,
                "appRoleId": role_id,
            })
            ok(f"  Consented: {perm_name} (Exchange)")
            granted += 1
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                ok(f"  Already consented: {perm_name} (Exchange)")
                granted += 1
            else:
                warn(f"  Failed: {perm_name} — {str(e)[:100]}")

    ok(f"Admin consent: {granted}/{total} permissions granted")
    return granted == total


def step_assign_exchange_admin_role(token, app_sp_id):
    """Assign Exchange Administrator directory role via roleManagement API."""
    info("Assigning Exchange Administrator role ...")

    resp = requests.post(
        f"{GRAPH_URL}/roleManagement/directory/roleAssignments",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "principalId": app_sp_id,
            "roleDefinitionId": EXCHANGE_ADMIN_ROLE_ID,
            "directoryScopeId": "/",
        },
    )

    if resp.status_code in (200, 201):
        ok("Exchange Administrator role assigned!")
        return True
    elif resp.status_code == 409 or "already exists" in resp.text.lower():
        ok("Exchange Administrator role already assigned")
        return True
    else:
        warn(f"Role assignment response ({resp.status_code}): {resp.text[:200]}")
        return False


def step_upload_certificate(token, app_object_id, cert_pem_b64, thumbprint):
    """PATCH keyCredentials to upload certificate."""
    from datetime import timedelta, timezone
    now = datetime.now(timezone.utc)
    # Graph API expects dates in format "2028-12-31T23:59:59Z"
    start = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (now + timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ")
    info("Uploading certificate ...")
    api_patch(token, f"{GRAPH_URL}/applications/{app_object_id}", {
        "keyCredentials": [{
            "type": "AsymmetricX509Cert",
            "usage": "Verify",
            "key": cert_pem_b64,
            "displayName": "automation-cert",
            "startDateTime": start,
            "endDateTime": end,
        }]
    })
    ok("Certificate uploaded")
