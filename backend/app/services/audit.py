"""Audit event logging helper."""

from sqlalchemy.ext.asyncio import AsyncSession


async def log_audit(
    db: AsyncSession,
    event_type: str,
    tenant_id=None,
    job_id=None,
    actor: str = "api",
    payload: dict | None = None,
):
    """Write an audit event to the database.

    Does NOT commit — the caller should commit as part of their transaction.
    """
    from app.models.workflow import AuditEvent

    event = AuditEvent(
        tenant_id=tenant_id,
        job_id=job_id,
        event_type=event_type,
        actor=actor,
        payload=payload or {},
    )
    db.add(event)
