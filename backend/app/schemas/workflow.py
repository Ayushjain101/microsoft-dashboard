"""Workflow schemas for API v2."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WorkflowStepOut(BaseModel):
    id: UUID
    step_index: int
    step_name: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None = None
    detail: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class WorkflowJobOut(BaseModel):
    id: UUID
    tenant_id: UUID
    job_type: str
    status: str
    config: dict | None = None
    current_step_index: int | None = None
    total_steps: int | None = None
    celery_task_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    steps: list[WorkflowStepOut] = []

    model_config = {"from_attributes": True}


class WorkflowJobCreate(BaseModel):
    """Used internally — not directly exposed to API."""
    tenant_id: UUID
    job_type: str
    config: dict | None = None
    idempotency_key: str | None = None


class RetryRequest(BaseModel):
    step_index: int | None = None  # If None, retry from first failed step
