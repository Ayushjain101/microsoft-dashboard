"""Celery task: 13-step Selenium tenant setup."""

import traceback
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models import Tenant
from app.services.encryption import encrypt, encrypt_bytes
from app.tasks.celery_app import celery_app
from app.websocket import publish_event_sync

sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True, pool_recycle=3600)

STEPS = [
    "Browser Login", "Security Setup", "Create App Registration",
    "Create Service Principal", "Create Client Secret", "Generate Certificate",
    "Add API Permissions", "Grant Admin Consent", "Assign Exchange Admin Role",
    "Save Credentials", "Finalize", "Grant Instantly Consent", "Delete MFA Authenticator",
]


def _publish_progress(tenant_id: str, step: int, total: int, message: str, status: str = "running"):
    """Publish progress to WebSocket via Redis and update DB."""
    publish_event_sync("tenant_setup_progress", {
        "tenant_id": tenant_id,
        "step": step,
        "total": total,
        "message": message,
        "status": status,
    })
    # Update DB
    with Session(sync_engine) as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant:
            tenant.status = status
            tenant.current_step = f"Step {step}/{total}: {message}"
            tenant.updated_at = datetime.now(timezone.utc)
            db.commit()


def _record_step_result(tenant_id: str, step: int, status: str, detail: str | None = None):
    """Record per-step result in the tenant's step_results JSON column."""
    with Session(sync_engine) as db:
        tenant = db.get(Tenant, tenant_id)
        if not tenant:
            return
        results = tenant.step_results or {}
        entry = {"status": status, "message": STEPS[step - 1]}
        if detail:
            entry["detail"] = detail
        results[str(step)] = entry
        tenant.step_results = results
        flag_modified(tenant, "step_results")
        db.commit()

    publish_event_sync("tenant_step_result", {
        "tenant_id": tenant_id, "step": step, "step_status": status,
        "message": STEPS[step - 1], "detail": detail,
    })


@celery_app.task(name="app.tasks.tenant_setup.run_tenant_setup", bind=True, queue="tenant_setup")
def run_tenant_setup(self, tenant_id: str):
    """Run the 12-step Selenium setup for a tenant.

    This task runs on the Selenium worker (15.204.174.187).
    """
    from app.services.encryption import decrypt

    with Session(sync_engine) as db:
        tenant = db.get(Tenant, tenant_id)
        if not tenant:
            return {"status": "error", "reason": "tenant_not_found"}

        # Idempotency: skip if already completed
        if tenant.status == "complete":
            return {"status": "complete", "reason": "already_complete"}

        email = tenant.admin_email
        password = decrypt(tenant.admin_password) if tenant.admin_password else ""
        new_password = decrypt(tenant.new_password) if tenant.new_password else None
        mfa_secret = decrypt(tenant.mfa_secret) if tenant.mfa_secret else None

    total = 13

    try:
        # Clear previous step_results on new run
        with Session(sync_engine) as db:
            tenant = db.get(Tenant, tenant_id)
            if tenant:
                tenant.step_results = {}
                flag_modified(tenant, "step_results")
                db.commit()

        _publish_progress(tenant_id, 0, total, "Starting setup", "running")

        # Import selenium worker modules
        from app.selenium_worker.setup_tenant import setup_single_tenant

        # Run the adapted setup function with progress callback
        def on_progress(step: int, message: str):
            _publish_progress(tenant_id, step, total, message)

        def on_step_result(step: int, status: str, detail: str | None = None):
            _record_step_result(tenant_id, step, status, detail)

        result = setup_single_tenant(
            email=email,
            password=password,
            new_password=new_password,
            mfa_secret=mfa_secret,
            progress_callback=on_progress,
            step_result_callback=on_step_result,
        )

        # Always save partial results (password change, mfa_secret, etc.) even on failure
        def _save_partial_results(result_data, db_session):
            tenant = db_session.get(Tenant, tenant_id)
            if not tenant:
                return
            if result_data.get("admin_password") and result_data["admin_password"] != password:
                tenant.admin_password = encrypt(result_data["admin_password"])
            if result_data.get("mfa_secret"):
                tenant.mfa_secret = encrypt(result_data["mfa_secret"])
            if result_data.get("tenant_id"):
                tenant.tenant_id_ms = encrypt(result_data["tenant_id"])
            if result_data.get("client_id"):
                tenant.client_id = encrypt(result_data["client_id"])
            if result_data.get("client_secret"):
                tenant.client_secret = encrypt(result_data["client_secret"])

        # Save results to DB
        if result.get("status") != "complete":
            error_msg = result.get("error", f"Setup failed at: {result.get('status', 'unknown')}")
            # Record the failed step if we can determine it
            failed_step = result.get("failed_step")
            if failed_step:
                _record_step_result(tenant_id, failed_step, "failed", error_msg[:500])
            with Session(sync_engine) as db:
                _save_partial_results(result, db)
                tenant = db.get(Tenant, tenant_id)
                if tenant:
                    tenant.status = "failed"
                    tenant.error_message = error_msg[:2000]
                db.commit()
            _publish_progress(tenant_id, 0, total, f"Failed: {error_msg}", "failed")
            return {"status": "failed", "error": error_msg}

        with Session(sync_engine) as db:
            tenant = db.get(Tenant, tenant_id)
            if tenant:
                if result.get("tenant_id"):
                    tenant.tenant_id_ms = encrypt(result["tenant_id"])
                if result.get("client_id"):
                    tenant.client_id = encrypt(result["client_id"])
                if result.get("client_secret"):
                    tenant.client_secret = encrypt(result["client_secret"])
                if result.get("cert_password"):
                    tenant.cert_password = encrypt(result["cert_password"])
                if result.get("pfx_bytes"):
                    tenant.cert_pfx = encrypt_bytes(result["pfx_bytes"])
                if result.get("mfa_secret"):
                    tenant.mfa_secret = encrypt(result["mfa_secret"])
                if result.get("admin_password"):
                    tenant.admin_password = encrypt(result["admin_password"])
                tenant.status = "complete"
                tenant.current_step = None
                tenant.completed_at = datetime.now(timezone.utc)
                db.commit()

        _publish_progress(tenant_id, total, total, "Setup complete", "complete")
        return {"status": "complete", "tenant_id": tenant_id}

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        with Session(sync_engine) as db:
            tenant = db.get(Tenant, tenant_id)
            if tenant:
                tenant.status = "failed"
                tenant.error_message = error_msg[:2000]
                db.commit()

        _publish_progress(tenant_id, 0, total, f"Failed: {str(e)}", "failed")
        return {"status": "failed", "error": str(e)}
