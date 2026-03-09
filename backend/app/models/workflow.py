"""Workflow-related ORM models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class WorkflowJob(Base):
    """Replaces MailboxJob and Tenant setup tracking with unified workflow tracking."""
    __tablename__ = "workflow_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)  # tenant_setup, mailbox_pipeline, health_check
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, queued, running, complete, failed, cancelled
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # domain, mailbox_count, custom_names, cf_email, etc.
    current_step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    lock_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="WorkflowStep.step_index"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    temp_artifacts: Mapped[list["TempArtifactRecord"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class WorkflowStep(Base):
    """Per-step tracking for workflow jobs."""
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("job_id", "step_index"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_jobs.id", ondelete="CASCADE"), index=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, running, success, failed, warning, skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["WorkflowJob"] = relationship(back_populates="steps")


class AuditEvent(Base):
    """Event-sourced audit trail."""
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("idx_audit_tenant", "tenant_id"),
        Index("idx_audit_job", "job_id"),
        Index("idx_audit_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_jobs.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped["WorkflowJob | None"] = relationship(back_populates="audit_events")


class TempArtifactRecord(Base):
    """Track temp files for guaranteed cleanup."""
    __tablename__ = "temp_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_jobs.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["WorkflowJob"] = relationship(back_populates="temp_artifacts")
