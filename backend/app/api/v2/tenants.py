"""API v2 — Tenant workflow endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Tenant
from app.models.workflow import WorkflowJob
from app.schemas.workflow import WorkflowJobOut

router = APIRouter(prefix="/api/v2/tenants", tags=["tenants-v2"], dependencies=[Depends(check_auth)])


@router.post("/{tenant_id}/setup", response_model=WorkflowJobOut)
async def start_tenant_setup(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Start tenant setup via workflow engine."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status == "complete":
        raise HTTPException(status_code=400, detail="Tenant already set up")

    # Create workflow job
    job = WorkflowJob(
        tenant_id=tenant_id,
        job_type="tenant_setup",
        status="queued",
        config={},
        idempotency_key=f"tenant_setup:{tenant_id}",
    )
    db.add(job)
    tenant.status = "queued"
    await db.commit()
    await db.refresh(job)

    from app.tasks.workflow_tasks import run_workflow_job
    task = run_workflow_job.delay(str(job.id))
    job.celery_task_id = task.id
    await db.commit()

    return job


@router.post("/{tenant_id}/mailboxes", response_model=WorkflowJobOut)
async def start_mailbox_pipeline(
    tenant_id: uuid.UUID,
    domain: str,
    mailbox_count: int = 50,
    cf_email: str | None = None,
    cf_api_key: str | None = None,
    custom_names: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Start mailbox creation pipeline via workflow engine."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status != "complete":
        raise HTTPException(status_code=400, detail="Tenant must be fully set up first")

    config = {
        "domain": domain.strip().lower(),
        "mailbox_count": mailbox_count,
    }
    if cf_email:
        config["cf_email"] = cf_email
    if cf_api_key:
        from app.services.encryption import encrypt
        config["cf_api_key"] = cf_api_key  # Will be encrypted in task
    if custom_names:
        config["custom_names"] = custom_names

    job = WorkflowJob(
        tenant_id=tenant_id,
        job_type="mailbox_pipeline",
        status="queued",
        config=config,
        idempotency_key=f"mailbox:{tenant_id}:{domain}:{uuid.uuid4().hex[:8]}",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from app.tasks.workflow_tasks import run_workflow_job
    task = run_workflow_job.delay(str(job.id))
    job.celery_task_id = task.id
    await db.commit()

    return job
