"""Mailbox creation pipeline + list/export endpoints."""

import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Domain, Mailbox, MailboxJob, Tenant
from app.services.encryption import encrypt, decrypt

router = APIRouter(prefix="/api/v1/mailboxes", tags=["mailboxes"], dependencies=[Depends(check_auth)])


class MailboxCreateRequest(BaseModel):
    domain: str
    mailbox_count: int = 50
    cf_email: str | None = None
    cf_api_key: str | None = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or "." not in v or len(v) > 253:
            raise ValueError("Invalid domain format")
        return v

    @field_validator("mailbox_count")
    @classmethod
    def validate_mailbox_count(cls, v: int) -> int:
        if v < 1 or v > 500:
            raise ValueError("mailbox_count must be between 1 and 500")
        return v


class MailboxOut(BaseModel):
    id: str
    tenant_id: str
    display_name: str | None
    email: str
    smtp_enabled: bool
    last_monitor_status: str | None
    created_at: str


class MailboxJobOut(BaseModel):
    id: str
    tenant_id: str
    domain: str
    mailbox_count: int
    status: str
    current_phase: str | None
    error_message: str | None
    created_at: str
    completed_at: str | None


def _mailbox_to_out(m: Mailbox) -> dict:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "display_name": m.display_name,
        "email": m.email,
        "smtp_enabled": m.smtp_enabled,
        "last_monitor_status": m.last_monitor_status,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _job_to_out(j: MailboxJob) -> dict:
    return {
        "id": str(j.id),
        "tenant_id": str(j.tenant_id),
        "domain": j.domain,
        "mailbox_count": j.mailbox_count,
        "status": j.status,
        "current_phase": j.current_phase,
        "error_message": j.error_message,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
    }


@router.get("")
async def list_all_mailboxes(
    page: int = 1, per_page: int = 100,
    db: AsyncSession = Depends(get_db),
):
    query = select(Mailbox).order_by(Mailbox.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    mailboxes = result.scalars().all()
    return {"mailboxes": [_mailbox_to_out(m) for m in mailboxes]}


@router.get("/{tenant_id}/export")
async def export_mailboxes_csv(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Mailbox).where(Mailbox.tenant_id == tenant_id).order_by(Mailbox.email)
    )
    mailboxes = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "display_name", "password", "smtp_enabled"])
    for m in mailboxes:
        pwd = ""
        if m.password:
            try:
                pwd = decrypt(m.password)
            except Exception:
                pass
        writer.writerow([m.email, m.display_name or "", pwd, m.smtp_enabled])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=mailboxes_{tenant_id}.csv"},
    )


@router.get("/{tenant_id}")
async def list_tenant_mailboxes(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Mailbox).where(Mailbox.tenant_id == tenant_id).order_by(Mailbox.email)
    )
    mailboxes = result.scalars().all()
    return {"mailboxes": [_mailbox_to_out(m) for m in mailboxes]}


@router.post("/{tenant_id}/create", status_code=201)
async def create_mailboxes(
    tenant_id: uuid.UUID,
    body: MailboxCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status != "complete":
        raise HTTPException(status_code=409, detail="Tenant setup must be complete first")

    job = MailboxJob(
        tenant_id=tenant_id,
        domain=body.domain,
        mailbox_count=body.mailbox_count,
        cf_email=body.cf_email,
        cf_api_key=encrypt(body.cf_api_key) if body.cf_api_key else None,
        status="queued",
        current_phase="Queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from app.tasks.mailbox_pipeline import run_mailbox_pipeline
    task = run_mailbox_pipeline.delay(str(job.id))
    job.celery_task_id = task.id
    await db.commit()

    return _job_to_out(job)


# ── Mailbox Jobs ─────────────────────────────────────────────────────────

jobs_router = APIRouter(prefix="/api/v1/mailbox-jobs", tags=["mailbox-jobs"], dependencies=[Depends(check_auth)])


@jobs_router.get("")
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MailboxJob).order_by(MailboxJob.created_at.desc()))
    jobs = result.scalars().all()
    return {"jobs": [_job_to_out(j) for j in jobs]}


@jobs_router.post("/{job_id}/stop")
async def stop_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(MailboxJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.celery_task_id:
        from app.tasks.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    job.status = "stopped"
    await db.commit()
    return {"status": "stopped"}


# Note: jobs_router is included in main.py separately
