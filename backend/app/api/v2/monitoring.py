"""API v2 — Monitoring and audit endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Alert, Mailbox, Tenant
from app.models.workflow import AuditEvent, WorkflowJob
from app.schemas.monitoring import AuditEventOut, DashboardStats

router = APIRouter(prefix="/api/v2", tags=["monitoring-v2"], dependencies=[Depends(check_auth)])


@router.get("/monitoring/dashboard", response_model=DashboardStats)
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Get aggregate dashboard statistics."""
    total_tenants = (await db.execute(select(func.count(Tenant.id)))).scalar() or 0
    complete_tenants = (await db.execute(
        select(func.count(Tenant.id)).where(Tenant.status == "complete")
    )).scalar() or 0
    total_mailboxes = (await db.execute(select(func.count(Mailbox.id)))).scalar() or 0
    healthy_mailboxes = (await db.execute(
        select(func.count(Mailbox.id)).where(Mailbox.last_monitor_status == "healthy")
    )).scalar() or 0
    active_jobs = (await db.execute(
        select(func.count(WorkflowJob.id)).where(WorkflowJob.status.in_(["queued", "running"]))
    )).scalar() or 0
    failed_jobs = (await db.execute(
        select(func.count(WorkflowJob.id)).where(WorkflowJob.status == "failed")
    )).scalar() or 0
    active_alerts = (await db.execute(
        select(func.count(Alert.id)).where(Alert.acknowledged == False)  # noqa: E712
    )).scalar() or 0

    return DashboardStats(
        total_tenants=total_tenants,
        complete_tenants=complete_tenants,
        total_mailboxes=total_mailboxes,
        healthy_mailboxes=healthy_mailboxes,
        active_jobs=active_jobs,
        failed_jobs=failed_jobs,
        active_alerts=active_alerts,
    )


@router.get("/audit", response_model=list[AuditEventOut])
async def list_audit_events(
    tenant_id: UUID | None = None,
    job_id: UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Query paginated audit events."""
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc())
    if tenant_id:
        query = query.where(AuditEvent.tenant_id == tenant_id)
    if job_id:
        query = query.where(AuditEvent.job_id == job_id)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
