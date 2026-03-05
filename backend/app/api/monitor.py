"""Monitoring dashboard + alerts endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Alert, Mailbox, MonitorCheck, Tenant

router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"], dependencies=[Depends(check_auth)])


@router.get("/dashboard")
async def health_dashboard(db: AsyncSession = Depends(get_db)):
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
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    await db.commit()
    return {"status": "acknowledged"}


@router.get("/{tenant_id}/mailflow")
async def mailflow_history(tenant_id: uuid.UUID, limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Last N mailflow checks for a tenant."""
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


@router.get("/{tenant_id}")
async def tenant_health(tenant_id: uuid.UUID, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Health history for a specific tenant."""
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
