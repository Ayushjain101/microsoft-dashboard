"""Celery task: 12-step Selenium tenant setup."""

import traceback
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Tenant
from app.services.encryption import encrypt, encrypt_bytes
from app.tasks.celery_app import celery_app
from app.websocket import publish_event_sync

sync_engine = create_engine(settings.database_url_sync)


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


@celery_app.task(name="app.tasks.tenant_setup.run_tenant_setup", bind=True, queue="tenant_setup",
                 acks_late=True, reject_on_worker_lost=True)
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

    total = 12

    try:
        _publish_progress(tenant_id, 0, total, "Starting setup", "running")

        # Import selenium worker modules
        from app.selenium_worker.setup_tenant import setup_single_tenant

        # Run the adapted setup function with progress callback
        def on_progress(step: int, message: str):
            _publish_progress(tenant_id, step, total, message)

        result = setup_single_tenant(
            email=email,
            password=password,
            new_password=new_password,
            progress_callback=on_progress,
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
