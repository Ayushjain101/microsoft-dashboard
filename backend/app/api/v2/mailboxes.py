"""API v2 — Mailbox + MailboxJob endpoints."""

import csv
import io
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Domain, Mailbox, MailboxJob, Tenant
from app.services.audit import log_audit
from app.services.encryption import encrypt, decrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/mailboxes", tags=["mailboxes-v2"], dependencies=[Depends(check_auth)])


# ── Schemas ──────────────────────────────────────────────────────────────

class BulkMailboxItem(BaseModel):
    tenant_id: str
    domain: str
    mailbox_count: int = 50
    cf_email: str | None = None
    cf_api_key: str | None = None
    custom_names: list[str] | None = None

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

    @field_validator("custom_names")
    @classmethod
    def validate_custom_names(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        v = [n.strip() for n in v if n.strip()]
        if not v:
            return None
        for name in v:
            parts = name.split()
            if len(parts) < 2:
                raise ValueError(f"Each name must have first and last name: '{name}'")
        return v


class BulkMailboxRequest(BaseModel):
    items: list[BulkMailboxItem]
    cf_email: str | None = None
    cf_api_key: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────

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


def _job_to_out(j: MailboxJob, dkim_enabled: bool = False) -> dict:
    return {
        "id": str(j.id),
        "tenant_id": str(j.tenant_id),
        "domain": j.domain,
        "mailbox_count": j.mailbox_count,
        "status": j.status,
        "current_phase": j.current_phase,
        "error_message": j.error_message,
        "step_results": j.step_results,
        "dkim_enabled": dkim_enabled,
        "health_results": j.health_results,
        "last_health_check": j.last_health_check.isoformat() if j.last_health_check else None,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
    }


async def _get_dkim_status(db: AsyncSession, tenant_id, domain: str) -> bool:
    """Look up DKIM status from the Domain table."""
    result = await db.execute(
        select(Domain.dkim_enabled).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
    )
    row = result.scalar_one_or_none()
    return bool(row) if row is not None else False


async def _bulk_create_jobs(
    items: list[BulkMailboxItem],
    shared_cf_email: str | None,
    shared_cf_api_key: str | None,
    db: AsyncSession,
):
    """Shared logic for bulk mailbox creation."""
    from app.tasks.mailbox_pipeline import run_mailbox_pipeline

    # Check for duplicate domains in request
    domains = [item.domain for item in items]
    if len(domains) != len(set(domains)):
        raise HTTPException(status_code=400, detail="Duplicate domains in request")

    created_jobs = []
    errors = []

    for item in items:
        try:
            tenant_id = uuid.UUID(item.tenant_id)
        except ValueError:
            errors.append({"tenant_id": item.tenant_id, "error": "Invalid tenant ID format"})
            continue

        tenant = await db.get(Tenant, tenant_id)
        if not tenant:
            errors.append({"tenant_id": item.tenant_id, "error": "Tenant not found"})
            continue
        if tenant.status != "complete":
            errors.append({"tenant_id": item.tenant_id, "error": "Tenant setup must be complete first"})
            continue

        cf_email = item.cf_email or shared_cf_email
        cf_api_key = item.cf_api_key or shared_cf_api_key

        job = MailboxJob(
            tenant_id=tenant_id,
            domain=item.domain,
            mailbox_count=item.mailbox_count,
            cf_email=cf_email,
            cf_api_key=encrypt(cf_api_key) if cf_api_key else None,
            custom_names=item.custom_names,
            status="queued",
            current_phase="Queued",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        await log_audit(
            db, "mailbox.bulk_pipeline_started", tenant_id=tenant_id,
            payload={"mailbox_job_id": str(job.id), "domain": item.domain, "mailbox_count": item.mailbox_count},
        )

        task = run_mailbox_pipeline.delay(str(job.id))
        job.celery_task_id = task.id
        await db.commit()

        created_jobs.append({"id": str(job.id), "tenant_id": str(job.tenant_id), "domain": job.domain})

    return {"created": len(created_jobs), "jobs": created_jobs, "errors": errors}


# ── Mailbox List Endpoints ───────────────────────────────────────────────

@router.get("")
async def list_all_mailboxes(
    page: int = 1, per_page: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """List all mailboxes (paginated)."""
    query = select(Mailbox).order_by(Mailbox.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    mailboxes = result.scalars().all()
    return {"mailboxes": [_mailbox_to_out(m) for m in mailboxes]}


@router.get("/tenant/{tenant_id}")
async def list_tenant_mailboxes(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List mailboxes for a specific tenant."""
    result = await db.execute(
        select(Mailbox).where(Mailbox.tenant_id == tenant_id).order_by(Mailbox.email)
    )
    mailboxes = result.scalars().all()
    return {"mailboxes": [_mailbox_to_out(m) for m in mailboxes]}


@router.get("/tenant/{tenant_id}/export")
async def export_mailboxes_csv(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Export mailboxes for a tenant as CSV."""
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
                logger.warning(f"Failed to decrypt password for mailbox {m.email}", exc_info=True)
        writer.writerow([m.email, m.display_name or "", pwd, m.smtp_enabled])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=mailboxes_{tenant_id}.csv"},
    )


@router.get("/export-all")
async def export_all_mailboxes_csv(
    tenant_ids: str | None = Query(None, description="Comma-separated tenant IDs"),
    db: AsyncSession = Depends(get_db),
):
    """Export mailboxes across all (or selected) tenants as a single CSV."""
    query = select(Mailbox).order_by(Mailbox.email)
    if tenant_ids:
        id_list = [uuid.UUID(i.strip()) for i in tenant_ids.split(",") if i.strip()]
        query = query.where(Mailbox.tenant_id.in_(id_list))

    result = await db.execute(query)
    mailboxes = result.scalars().all()

    # Build tenant name lookup
    t_ids = list({m.tenant_id for m in mailboxes})
    tenant_names: dict[uuid.UUID, str] = {}
    if t_ids:
        t_result = await db.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_(t_ids)))
        for tid, tname in t_result.all():
            tenant_names[tid] = tname

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["tenant_name", "email", "display_name", "password", "smtp_enabled"])
    for m in mailboxes:
        pwd = ""
        if m.password:
            try:
                pwd = decrypt(m.password)
            except Exception:
                logger.warning(f"Failed to decrypt password for mailbox {m.email}", exc_info=True)
        writer.writerow([
            tenant_names.get(m.tenant_id, ""),
            m.email,
            m.display_name or "",
            pwd,
            m.smtp_enabled,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=all_mailboxes_export.csv"},
    )


# ── Bulk Create Endpoints ────────────────────────────────────────────────

@router.post("/bulk-create", status_code=201)
async def bulk_create_mailboxes(body: BulkMailboxRequest, db: AsyncSession = Depends(get_db)):
    """Bulk create mailbox pipelines from JSON."""
    if not body.items:
        raise HTTPException(status_code=400, detail="No items provided")
    return await _bulk_create_jobs(body.items, body.cf_email, body.cf_api_key, db)


@router.post("/bulk-create-csv", status_code=201)
async def bulk_create_mailboxes_csv(
    file: UploadFile = File(...),
    cf_email: Optional[str] = Query(None),
    cf_api_key: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Bulk create mailbox pipelines from CSV file."""
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid file encoding, expected UTF-8")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "tenant_email" not in reader.fieldnames or "domain" not in reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV must have 'tenant_email' and 'domain' columns")

    items = []
    errors = []
    for row_num, row in enumerate(reader, start=2):
        tenant_email = row.get("tenant_email", "").strip()
        domain = row.get("domain", "").strip()
        count_str = row.get("count", "50").strip()

        if not tenant_email or not domain:
            errors.append({"tenant_id": tenant_email or f"row {row_num}", "error": "Missing tenant_email or domain"})
            continue

        try:
            count_val = int(count_str) if count_str else 50
            count_val = max(1, min(500, count_val))
        except ValueError:
            errors.append({"tenant_id": tenant_email, "error": f"Invalid count: {count_str}"})
            continue

        # Resolve tenant by admin_email
        result = await db.execute(select(Tenant).where(Tenant.admin_email == tenant_email))
        tenant = result.scalar_one_or_none()
        if not tenant:
            errors.append({"tenant_id": tenant_email, "error": "Tenant not found for this email"})
            continue

        # Parse optional custom_names column (pipe-delimited)
        custom_names_str = row.get("custom_names", "").strip()
        custom_names = [n.strip() for n in custom_names_str.split("|") if n.strip()] if custom_names_str else None

        items.append(BulkMailboxItem(
            tenant_id=str(tenant.id), domain=domain, mailbox_count=count_val,
            custom_names=custom_names,
        ))

    if not items and errors:
        return {"created": 0, "jobs": [], "errors": errors}

    result = await _bulk_create_jobs(items, cf_email, cf_api_key, db)
    result["errors"].extend(errors)
    return result


# ── Jobs Endpoints ───────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """List all mailbox jobs with step results, health results, DKIM status."""
    result = await db.execute(select(MailboxJob).order_by(MailboxJob.created_at.desc()))
    jobs = result.scalars().all()
    out = []
    for j in jobs:
        dkim = await _get_dkim_status(db, j.tenant_id, j.domain)
        out.append(_job_to_out(j, dkim_enabled=dkim))
    return {"jobs": out}


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Stop a running mailbox job."""
    job = await db.get(MailboxJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.celery_task_id:
        from app.tasks.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    job.status = "stopped"
    await log_audit(db, "mailbox.job_stopped", tenant_id=job.tenant_id,
                    payload={"mailbox_job_id": str(job.id)})
    await db.commit()
    return {"status": "stopped"}


@router.post("/jobs/{job_id}/health-check")
async def health_check_mailboxes(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Run health check on mailboxes for a job."""
    job = await db.get(MailboxJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("complete", "failed"):
        raise HTTPException(status_code=409, detail="Job must be complete or failed to run health check")

    from app.tasks.mailbox_pipeline import run_mailbox_health_check
    run_mailbox_health_check.apply_async(args=[str(job.id)], kwargs={"force": True})
    return {"status": "queued"}


@router.post("/jobs/{job_id}/retry-missing")
async def retry_missing_mailboxes(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Retry creating missing mailboxes for a job."""
    job = await db.get(MailboxJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("complete", "failed"):
        raise HTTPException(status_code=409, detail="Job must be complete or failed to retry missing")

    from app.tasks.mailbox_pipeline import retry_missing_mailboxes as retry_task
    await log_audit(db, "mailbox.retry_missing", tenant_id=job.tenant_id,
                    payload={"mailbox_job_id": str(job.id)})
    await db.commit()
    retry_task.delay(str(job.id))
    return {"status": "queued"}


@router.post("/jobs/{job_id}/enable-dkim")
async def enable_dkim(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Enable DKIM for a completed mailbox job."""
    job = await db.get(MailboxJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "complete":
        raise HTTPException(status_code=409, detail="Job must be complete before enabling DKIM")

    from app.tasks.mailbox_pipeline import enable_dkim_task
    await log_audit(db, "mailbox.dkim_enabled", tenant_id=job.tenant_id,
                    payload={"mailbox_job_id": str(job.id), "domain": job.domain})
    await db.commit()
    enable_dkim_task.delay(str(job.id))
    return {"status": "queued"}


# ── Single Mailbox Endpoints ─────────────────────────────────────────────

@router.post("/{mailbox_id}/retry")
async def retry_mailbox(mailbox_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Retry provisioning for a single mailbox (placeholder for per-mailbox tracking)."""
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    # TODO: Implement per-mailbox retry using provision_status
    return {"status": "not_implemented", "detail": "Per-mailbox retry will be available after provision_status migration"}
