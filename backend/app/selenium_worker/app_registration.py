"""App Registration, permissions, admin consent, and role assignment via Graph API.

Adapted from selenium-setup/app_registration.py — uses logging instead of print.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.microsoft.com/v1.0"
MICROSOFT_GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
OFFICE365_EXCHANGE_APP_ID = "00000002-0000-0ff1-ce00-000000000000"
EXCHANGE_ADMIN_ROLE_ID = "29232cdf-9323-42fd-ade2-1d097af3e4de"

REQUIRED_GRAPH_PERMISSIONS = [
    "User.ReadWrite.All", "Directory.ReadWrite.All", "Application.ReadWrite.All",
    "Domain.ReadWrite.All", "Organization.ReadWrite.All",
    "Policy.ReadWrite.ConditionalAccess", "Policy.ReadWrite.AuthenticationMethod",
    "Policy.ReadWrite.SecurityDefaults", "Policy.Read.All",
    "UserAuthenticationMethod.ReadWrite.All", "Mail.ReadWrite", "Mail.Send",
]
REQUIRED_GRAPH_DELEGATED = ["SMTP.Send"]
REQUIRED_EXCHANGE_PERMISSIONS = ["full_access_as_app", "Exchange.ManageAsApp"]


def api_get(token, url):
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def api_post(token, url, body):
    resp = requests.post(url, json=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    }, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"POST {url} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.text else {}


def api_patch(token, url, body):
    resp = requests.patch(url, json=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    }, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"PATCH {url} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.text else {}


def lookup_sp_roles(token, app_id):
    data = api_get(token,
        f"{GRAPH_URL}/servicePrincipals?$filter=appId eq '{app_id}'"
        f"&$select=id,appId,appRoles,oauth2PermissionScopes")
    if not data.get("value"):
        raise RuntimeError(f"Service principal not found for appId {app_id}")
    sp = data["value"][0]
    roles = {r["value"]: r["id"] for r in sp.get("appRoles", [])}
    scopes = {s["value"]: s["id"] for s in sp.get("oauth2PermissionScopes", [])}
    return sp["id"], roles, scopes


def step_create_app(token, app_name):
    logger.info(f"Creating App Registration: '{app_name}' ...")
    result = api_post(token, f"{GRAPH_URL}/applications", {
        "displayName": app_name, "signInAudience": "AzureADMyOrg",
    })
    app_object_id = result["id"]
    client_id = result["appId"]
    logger.info(f"App created — Client ID: {client_id}")
    return app_object_id, client_id


def step_create_secret(token, app_object_id):
    logger.info("Creating client secret ...")
    result = api_post(token, f"{GRAPH_URL}/applications/{app_object_id}/addPassword", {
        "passwordCredential": {"displayName": "AutoSetupSecret", "endDateTime": "2028-12-31T23:59:59Z"}
    })
    return result["secretText"]


def step_create_service_principal(token, client_id):
    logger.info("Creating service principal ...")
    try:
        result = api_post(token, f"{GRAPH_URL}/servicePrincipals", {"appId": client_id})
        return result["id"]
    except RuntimeError as e:
        err_lower = str(e).lower()
        if "already exists" in err_lower or "already in use" in err_lower or "409" in str(e):
            data = api_get(token,
                f"{GRAPH_URL}/servicePrincipals?$filter=appId eq '{client_id}'&$select=id")
            return data["value"][0]["id"]
        raise


def step_add_permissions(token, app_object_id):
    logger.info("Looking up permission IDs ...")
    graph_sp_id, graph_roles, graph_scopes = lookup_sp_roles(token, MICROSOFT_GRAPH_APP_ID)
    exchange_sp_id, exchange_roles, _ = lookup_sp_roles(token, OFFICE365_EXCHANGE_APP_ID)

    graph_resource_access = []
    for perm_name in REQUIRED_GRAPH_PERMISSIONS:
        role_id = graph_roles.get(perm_name)
        if role_id:
            graph_resource_access.append({"id": role_id, "type": "Role"})

    for perm_name in REQUIRED_GRAPH_DELEGATED:
        scope_id = graph_scopes.get(perm_name)
        if scope_id:
            graph_resource_access.append({"id": scope_id, "type": "Scope"})

    exchange_resource_access = []
    for perm_name in REQUIRED_EXCHANGE_PERMISSIONS:
        role_id = exchange_roles.get(perm_name)
        if role_id:
            exchange_resource_access.append({"id": role_id, "type": "Role"})

    required_access = []
    if graph_resource_access:
        required_access.append({"resourceAppId": MICROSOFT_GRAPH_APP_ID, "resourceAccess": graph_resource_access})
    if exchange_resource_access:
        required_access.append({"resourceAppId": OFFICE365_EXCHANGE_APP_ID, "resourceAccess": exchange_resource_access})

    api_patch(token, f"{GRAPH_URL}/applications/{app_object_id}", {"requiredResourceAccess": required_access})
    logger.info("All permissions added to app manifest")
    return graph_sp_id, graph_roles, graph_scopes, exchange_sp_id, exchange_roles


def step_grant_admin_consent(token, app_sp_id, graph_sp_id, graph_roles, graph_scopes,
                              exchange_sp_id, exchange_roles):
    logger.info("Granting admin consent ...")
    total, granted = 0, 0

    for perm_name in REQUIRED_GRAPH_PERMISSIONS:
        role_id = graph_roles.get(perm_name)
        if not role_id:
            continue
        total += 1
        try:
            api_post(token, f"{GRAPH_URL}/servicePrincipals/{app_sp_id}/appRoleAssignments", {
                "principalId": app_sp_id, "resourceId": graph_sp_id, "appRoleId": role_id,
            })
            granted += 1
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                granted += 1

    for perm_name in REQUIRED_EXCHANGE_PERMISSIONS:
        role_id = exchange_roles.get(perm_name)
        if not role_id:
            continue
        total += 1
        try:
            api_post(token, f"{GRAPH_URL}/servicePrincipals/{app_sp_id}/appRoleAssignments", {
                "principalId": app_sp_id, "resourceId": exchange_sp_id, "appRoleId": role_id,
            })
            granted += 1
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                granted += 1

    logger.info(f"Admin consent: {granted}/{total} permissions granted")
    return granted == total


def step_assign_exchange_admin_role(token, app_sp_id):
    logger.info("Assigning Exchange Administrator role ...")
    resp = requests.post(
        f"{GRAPH_URL}/roleManagement/directory/roleAssignments",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"principalId": app_sp_id, "roleDefinitionId": EXCHANGE_ADMIN_ROLE_ID, "directoryScopeId": "/"},
        timeout=30,
    )
    if resp.status_code in (200, 201):
        logger.info("Exchange Administrator role assigned!")
        return True
    elif resp.status_code == 409 or "already exists" in resp.text.lower():
        logger.info("Exchange Administrator role already assigned")
        return True
    else:
        logger.warning(f"Role assignment response ({resp.status_code}): {resp.text[:200]}")
        return False


def step_upload_certificate(token, app_object_id, cert_pem_b64, thumbprint,
                            not_valid_before=None, not_valid_after=None):
    if not_valid_before and not_valid_after:
        start = not_valid_before.strftime("%Y-%m-%dT%H:%M:%SZ")
        end = not_valid_after.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        now = datetime.now(timezone.utc)
        start = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (now + timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"Uploading certificate (valid {start} to {end}) ...")
    api_patch(token, f"{GRAPH_URL}/applications/{app_object_id}", {
        "keyCredentials": [{
            "type": "AsymmetricX509Cert", "usage": "Verify",
            "key": cert_pem_b64, "displayName": "automation-cert",
            "startDateTime": start, "endDateTime": end,
        }]
    })
    logger.info("Certificate uploaded")
