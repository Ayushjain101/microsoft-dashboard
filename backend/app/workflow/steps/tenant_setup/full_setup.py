"""Tenant setup — wraps existing selenium_worker as a single workflow step.

The 13 individual selenium steps are tracked via callbacks within this single
workflow step. Full decomposition into 13 separate BaseStep classes is deferred
to Phase 5, as it requires refactoring the selenium_worker module itself.
"""

import logging

from app.services.encryption import encrypt, encrypt_bytes
from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


class TenantSetupStep(BaseStep):
    name = "Tenant Setup (Selenium)"
    max_attempts = 1  # Selenium steps handle their own retries internally
    is_blocking = True

    def execute(self, ctx) -> StepResult:
        from app.services.encryption import decrypt
        from app.selenium_worker.setup_tenant import setup_single_tenant
        from app.models import Tenant

        tenant = ctx.db.get(Tenant, str(ctx.job.tenant_id))
        if not tenant:
            return StepResult(status="failed", detail="Tenant not found")

        email = tenant.admin_email
        password = decrypt(tenant.admin_password) if tenant.admin_password else ""
        new_password = decrypt(tenant.new_password) if tenant.new_password else None
        mfa_secret = decrypt(tenant.mfa_secret) if tenant.mfa_secret else None

        tenant_id = str(ctx.job.tenant_id)

        def on_progress(step: int, message: str):
            ctx.publish("tenant_setup_progress", {
                "tenant_id": tenant_id, "step": step, "total": 13,
                "message": message, "status": "running",
            })

        def on_step_result(step: int, status: str, detail: str | None = None):
            ctx.publish("tenant_step_result", {
                "tenant_id": tenant_id, "step": step,
                "step_status": status, "message": "", "detail": detail,
            })

        def on_mfa_secret(secret: str):
            tenant.mfa_secret = encrypt(secret)
            ctx.db.commit()

        def on_password_changed(new_pwd: str):
            tenant.admin_password = encrypt(new_pwd)
            ctx.db.commit()

        result = setup_single_tenant(
            email=email,
            password=password,
            new_password=new_password,
            mfa_secret=mfa_secret,
            progress_callback=on_progress,
            step_result_callback=on_step_result,
            on_mfa_secret=on_mfa_secret,
            on_password_changed=on_password_changed,
        )

        if result.get("status") != "complete":
            error_msg = result.get("error", f"Setup failed: {result.get('status', 'unknown')}")
            # Save partial results
            if result.get("admin_password") and result["admin_password"] != password:
                tenant.admin_password = encrypt(result["admin_password"])
            if result.get("mfa_secret"):
                tenant.mfa_secret = encrypt(result["mfa_secret"])
            if result.get("tenant_id"):
                tenant.tenant_id_ms = encrypt(result["tenant_id"])
            if result.get("client_id"):
                tenant.client_id = encrypt(result["client_id"])
            if result.get("client_secret"):
                tenant.client_secret = encrypt(result["client_secret"])
            ctx.db.commit()
            return StepResult(status="failed", detail=error_msg[:2000])

        # Save complete results
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
        ctx.db.commit()

        return StepResult(status="success", detail="All 13 setup steps completed")
