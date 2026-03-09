"""Monitoring schemas for API v2."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: int
    tenant_id: UUID | None = None
    job_id: UUID | None = None
    event_type: str
    actor: str
    payload: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DashboardStats(BaseModel):
    total_tenants: int
    complete_tenants: int
    total_mailboxes: int
    healthy_mailboxes: int
    active_jobs: int
    failed_jobs: int
    active_alerts: int
