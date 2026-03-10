"""API v2 — Monitoring, alerts, and audit endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Alert, Mailbox, MonitorCheck, Tenant
from app.models.workflow import AuditEvent, WorkflowJob
from app.schemas.monitoring import AuditEventOut, DashboardStats
from app.services.audit import log_audit

router = APIRouter(prefix="/api/v2/monitoring", tags=["monitoring-v2"], dependencies=[Depends(check_auth)])


@router.get("/dashboard")
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Health summary: counts by status across all tenants."""
    # Tenant counts
    result = await db.execute(select(Tenant.status, func.count()).group_by(Tenant.status))
    tenant_counts = {row[0]: row[1] for row in result.all()}

    # Mailbox counts
    result = await db.execute(select(func.count()).select_from(Mailbox))
    total_mailboxes = result.scalar() or 0

    # Recent checks summary
    result = await db.execute(
        select(MonitorCheck.status, func.count())
        .group_by(MonitorCheck.status)
        .order_by(func.count().desc())
    )
    check_counts = {row[0]: row[1] for row in result.all()}

    # Active alerts
    result = await db.execute(
        select(func.count()).select_from(Alert).where(
            Alert.acknowledged == False, Alert.resolved_at == None  # noqa: E712
        )
    )
    active_alerts = result.scalar() or 0

    # Mailflow check counts
    result = await db.execute(
        select(MonitorCheck.status, func.count())
        .where(MonitorCheck.check_type == "mailflow")
        .group_by(MonitorCheck.status)
    )
    mailflow_counts = {row[0]: row[1] for row in result.all()}

    return {
        "tenant_counts": tenant_counts,
        "total_mailboxes": total_mailboxes,
        "check_status_counts": check_counts,
        "active_alerts": active_alerts,
        "mailflow_counts": mailflow_counts,
    }


@router.get("/alerts")
async def list_alerts(
    acknowledged: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List alerts, optionally filtered by acknowledged status."""
    query = select(Alert).order_by(Alert.created_at.desc()).limit(200)
    if acknowledged is not None:
        query = query.where(Alert.acknowledged == acknowledged)
    result = await db.execute(query)
    alerts = result.scalars().all()
    return {
        "alerts": [
            {
                "id": a.id,
                "tenant_id": str(a.tenant_id),
                "alert_type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "acknowledged": a.acknowledged,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            }
            for a in alerts
        ]
    }


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    """Acknowledge an alert."""
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    await log_audit(db, "alert.acknowledged", tenant_id=alert.tenant_id,
                    payload={"alert_id": alert_id, "alert_type": alert.alert_type})
    await db.commit()
    return {"status": "acknowledged"}


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an alert."""
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()
    return {"status": "deleted"}


@router.post("/alerts/bulk-delete")
async def bulk_delete_alerts(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Bulk delete alerts. Body: { "ids": [1,2,3] } or { "all_acknowledged": true } or { "all": true }"""
    if body.get("all"):
        result = await db.execute(select(Alert))
        alerts = result.scalars().all()
        for a in alerts:
            await db.delete(a)
        await db.commit()
        return {"deleted": len(alerts)}
    elif body.get("all_acknowledged"):
        result = await db.execute(select(Alert).where(Alert.acknowledged == True))
        alerts = result.scalars().all()
        for a in alerts:
            await db.delete(a)
        await db.commit()
        return {"deleted": len(alerts)}
    elif body.get("ids"):
        ids = body["ids"]
        result = await db.execute(select(Alert).where(Alert.id.in_(ids)))
        alerts = result.scalars().all()
        for a in alerts:
            await db.delete(a)
        await db.commit()
        return {"deleted": len(alerts)}
    else:
        raise HTTPException(status_code=400, detail="Provide 'ids', 'all_acknowledged', or 'all'")


@router.post("/alerts/bulk-ack")
async def bulk_ack_alerts(db: AsyncSession = Depends(get_db)):
    """Acknowledge all unacknowledged alerts."""
    result = await db.execute(select(Alert).where(Alert.acknowledged == False))
    alerts = result.scalars().all()
    for a in alerts:
        a.acknowledged = True
        a.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"acknowledged": len(alerts)}


@router.get("/audit", response_model=list[AuditEventOut])
async def list_audit_events(
    tenant_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
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


@router.get("/{tenant_id}")
async def tenant_health(tenant_id: uuid.UUID, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Health history for a specific tenant."""
    limit = min(limit, 500)
    result = await db.execute(
        select(MonitorCheck)
        .where(MonitorCheck.tenant_id == tenant_id)
        .order_by(MonitorCheck.checked_at.desc())
        .limit(limit)
    )
    checks = result.scalars().all()
    return {
        "checks": [
            {
                "id": c.id,
                "check_type": c.check_type,
                "status": c.status,
                "detail": c.detail,
                "response_ms": c.response_ms,
                "checked_at": c.checked_at.isoformat() if c.checked_at else None,
            }
            for c in checks
        ]
    }


@router.get("/{tenant_id}/mailflow")
async def mailflow_history(tenant_id: uuid.UUID, limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Last N mailflow checks for a tenant."""
    limit = min(limit, 500)
    result = await db.execute(
        select(MonitorCheck)
        .where(MonitorCheck.tenant_id == tenant_id, MonitorCheck.check_type == "mailflow")
        .order_by(MonitorCheck.checked_at.desc())
        .limit(limit)
    )
    checks = result.scalars().all()
    return {
        "checks": [
            {
                "id": c.id,
                "status": c.status,
                "detail": c.detail,
                "checked_at": c.checked_at.isoformat() if c.checked_at else None,
            }
            for c in checks
        ]
    }


@router.post("/{tenant_id}/check-now")
async def trigger_check(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Trigger an immediate health check for a tenant."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    from app.tasks.monitor import run_tenant_check, run_mailflow_check
    run_tenant_check.delay(str(tenant_id))
    run_mailflow_check.delay(str(tenant_id))
    return {"status": "queued"}
