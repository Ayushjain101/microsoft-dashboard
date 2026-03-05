"""Celery task: 8-check tenant health verification."""

import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models import Tenant
from app.services.encryption import decrypt
from app.tasks.celery_app import celery_app
from app.websocket import publish_event_sync

logger = logging.getLogger(__name__)
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True, pool_recycle=3600)

INSTANTLY_APP_ID = "65ad96b6-fbeb-40b5-b404-2a415d074c97"

HEALTH_CHECKS = [
    "Credentials Exist",
    "Token Acquisition",
    "App Registration",
    "Service Principal",
    "Graph Permissions",
    "Exchange Admin Role",
    "Certificate Valid",
    "Instantly Consent",
]


def _decrypt_safe(val):
    if val is None:
        return None
    try:
        return decrypt(val)
    except Exception:
        return None


@celery_app.task(name="app.tasks.tenant_health.run_tenant_health_check", bind=True, queue="default")
def run_tenant_health_check(self, tenant_id: str):
    """Run 8 health checks against a tenant's Azure configuration."""
    results = {}

    with Session(sync_engine) as db:
        tenant = db.get(Tenant, tenant_id)
        if not tenant:
            return {"status": "error", "reason": "tenant_not_found"}

        tenant_id_ms = _decrypt_safe(tenant.tenant_id_ms)
        client_id = _decrypt_safe(tenant.client_id)
        client_secret = _decrypt_safe(tenant.client_secret)
        cert_pfx = tenant.cert_pfx
        cert_password = _decrypt_safe(tenant.cert_password)

    # Check 1: Credentials Exist
    missing = []
    if not tenant_id_ms:
        missing.append("tenant_id_ms")
    if not client_id:
        missing.append("client_id")
    if not client_secret:
        missing.append("client_secret")
    if not cert_pfx:
        missing.append("cert_pfx")
    if not cert_password:
        missing.append("cert_password")

    if missing:
        results["1"] = {"status": "fail", "message": HEALTH_CHECKS[0], "detail": f"Missing: {', '.join(missing)}"}
    else:
        results["1"] = {"status": "pass", "message": HEALTH_CHECKS[0]}

    # If we can't even get basic creds, skip the rest
    if not tenant_id_ms or not client_id or not client_secret:
        for i in range(2, 9):
            results[str(i)] = {"status": "skip", "message": HEALTH_CHECKS[i - 1], "detail": "Skipped — missing credentials"}
        _save_results(tenant_id, results)
        return {"status": "complete", "results": results}

    # Check 2: Token Acquisition
    try:
        from app.services.graph_client import MicrosoftGraphClient
        graph = MicrosoftGraphClient(tenant_id_ms, client_id, client_secret)
        graph._acquire_token()
        results["2"] = {"status": "pass", "message": HEALTH_CHECKS[1]}
    except Exception as e:
        results["2"] = {"status": "fail", "message": HEALTH_CHECKS[1], "detail": str(e)[:500]}
        # Can't proceed without token
        for i in range(3, 9):
            results[str(i)] = {"status": "skip", "message": HEALTH_CHECKS[i - 1], "detail": "Skipped — token acquisition failed"}
        _save_results(tenant_id, results)
        return {"status": "complete", "results": results}

    # Check 3: App Registration
    app_object_id = None
    try:
        resp = graph.get(f"/applications?$filter=appId eq '{client_id}'")
        apps = resp.json().get("value", [])
        if apps:
            app_object_id = apps[0]["id"]
            results["3"] = {"status": "pass", "message": HEALTH_CHECKS[2]}
        else:
            results["3"] = {"status": "fail", "message": HEALTH_CHECKS[2], "detail": "App registration not found"}
    except Exception as e:
        results["3"] = {"status": "fail", "message": HEALTH_CHECKS[2], "detail": str(e)[:500]}

    # Check 4: Service Principal
    sp_id = None
    try:
        resp = graph.get(f"/servicePrincipals?$filter=appId eq '{client_id}'")
        sps = resp.json().get("value", [])
        if sps:
            sp_id = sps[0]["id"]
            results["4"] = {"status": "pass", "message": HEALTH_CHECKS[3]}
        else:
            results["4"] = {"status": "fail", "message": HEALTH_CHECKS[3], "detail": "Service principal not found"}
    except Exception as e:
        results["4"] = {"status": "fail", "message": HEALTH_CHECKS[3], "detail": str(e)[:500]}

    # Check 5: Graph Permissions
    if sp_id:
        try:
            resp = graph.get(f"/servicePrincipals/{sp_id}/appRoleAssignments")
            assignments = resp.json().get("value", [])
            count = len(assignments)
            if count >= 10:
                results["5"] = {"status": "pass", "message": HEALTH_CHECKS[4], "detail": f"{count} permissions granted"}
            else:
                results["5"] = {"status": "fail", "message": HEALTH_CHECKS[4], "detail": f"Only {count} permissions (expected >= 10)"}
        except Exception as e:
            results["5"] = {"status": "fail", "message": HEALTH_CHECKS[4], "detail": str(e)[:500]}
    else:
        results["5"] = {"status": "skip", "message": HEALTH_CHECKS[4], "detail": "Skipped — no service principal"}

    # Check 6: Exchange Admin Role (via unified RBAC API)
    EXCHANGE_ADMIN_ROLE_ID = "29232cdf-9323-42fd-ade2-1d097af3e4de"
    if sp_id:
        try:
            resp = graph.get(
                f"/roleManagement/directory/roleAssignments?$filter=principalId eq '{sp_id}' and roleDefinitionId eq '{EXCHANGE_ADMIN_ROLE_ID}'"
            )
            assignments = resp.json().get("value", [])
            if assignments:
                results["6"] = {"status": "pass", "message": HEALTH_CHECKS[5]}
            else:
                results["6"] = {"status": "fail", "message": HEALTH_CHECKS[5], "detail": "Service principal is not Exchange Admin"}
        except Exception as e:
            results["6"] = {"status": "fail", "message": HEALTH_CHECKS[5], "detail": str(e)[:500]}
    else:
        results["6"] = {"status": "skip", "message": HEALTH_CHECKS[5], "detail": "Skipped — no service principal"}

    # Check 7: Certificate Valid
    if app_object_id:
        try:
            resp = graph.get(f"/applications/{app_object_id}")
            app_data = resp.json()
            key_creds = app_data.get("keyCredentials", [])
            if not key_creds:
                results["7"] = {"status": "fail", "message": HEALTH_CHECKS[6], "detail": "No certificate found on app"}
            else:
                # Check if any cert is still valid
                now = datetime.now(timezone.utc).isoformat()
                valid = any(kc.get("endDateTime", "") > now for kc in key_creds)
                if valid:
                    results["7"] = {"status": "pass", "message": HEALTH_CHECKS[6]}
                else:
                    results["7"] = {"status": "fail", "message": HEALTH_CHECKS[6], "detail": "All certificates expired"}
        except Exception as e:
            results["7"] = {"status": "fail", "message": HEALTH_CHECKS[6], "detail": str(e)[:500]}
    else:
        results["7"] = {"status": "skip", "message": HEALTH_CHECKS[6], "detail": "Skipped — app registration not found"}

    # Check 8: Instantly Consent
    try:
        # Find Instantly SP
        resp = graph.get(f"/servicePrincipals?$filter=appId eq '{INSTANTLY_APP_ID}'")
        instantly_sps = resp.json().get("value", [])
        if instantly_sps:
            instantly_sp_id = instantly_sps[0]["id"]
            grants_resp = graph.get(f"/oauth2PermissionGrants?$filter=clientId eq '{instantly_sp_id}'")
            grants = grants_resp.json().get("value", [])
            if grants:
                results["8"] = {"status": "pass", "message": HEALTH_CHECKS[7]}
            else:
                results["8"] = {"status": "warn", "message": HEALTH_CHECKS[7], "detail": "No permission grants found for Instantly"}
        else:
            results["8"] = {"status": "warn", "message": HEALTH_CHECKS[7], "detail": "Instantly service principal not found"}
    except Exception as e:
        results["8"] = {"status": "warn", "message": HEALTH_CHECKS[7], "detail": str(e)[:500]}

    _save_results(tenant_id, results)
    return {"status": "complete", "results": results}


def _save_results(tenant_id: str, results: dict):
    """Save health check results to DB and publish WebSocket event."""
    now = datetime.now(timezone.utc)
    with Session(sync_engine) as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant:
            tenant.health_results = results
            flag_modified(tenant, "health_results")
            tenant.last_health_check = now
            db.commit()

    publish_event_sync("tenant_health_check", {
        "tenant_id": tenant_id,
        "health_results": results,
        "last_health_check": now.isoformat(),
    })
