"""Unit of Work pattern — wraps DB session + audit event collection."""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AuditEvent


class UnitOfWork:
    """Collects audit events and commits them atomically with other DB changes."""

    def __init__(self, db: Session, actor: str = "system"):
        self.db = db
        self.actor = actor
        self._pending_events: list[dict] = []

    def add_event(
        self,
        event_type: str,
        tenant_id: uuid.UUID | str | None = None,
        job_id: uuid.UUID | str | None = None,
        payload: dict | None = None,
    ):
        self._pending_events.append({
            "event_type": event_type,
            "tenant_id": uuid.UUID(str(tenant_id)) if tenant_id else None,
            "job_id": uuid.UUID(str(job_id)) if job_id else None,
            "actor": self.actor,
            "payload": payload or {},
        })

    def flush_events(self):
        """Write pending audit events to the DB (call before commit)."""
        for evt in self._pending_events:
            self.db.add(AuditEvent(
                tenant_id=evt["tenant_id"],
                job_id=evt["job_id"],
                event_type=evt["event_type"],
                actor=evt["actor"],
                payload=evt["payload"],
                created_at=datetime.now(timezone.utc),
            ))
        self._pending_events.clear()

    def commit(self):
        """Flush events and commit the session."""
        self.flush_events()
        self.db.commit()

    def rollback(self):
        """Rollback and discard pending events."""
        self._pending_events.clear()
        self.db.rollback()
