"""Models package — re-exports all ORM models."""

# Existing models (from original models.py, kept for backward compat)
from app.models_legacy import (
    Alert,
    AppSetting,
    CloudflareConfig,
    Domain,
    Mailbox,
    MailboxJob,
    MonitorCheck,
    Tenant,
    utcnow,
)

# New models
from app.models.workflow import AuditEvent, TempArtifactRecord, WorkflowJob, WorkflowStep

__all__ = [
    # Legacy
    "Alert",
    "AppSetting",
    "CloudflareConfig",
    "Domain",
    "Mailbox",
    "MailboxJob",
    "MonitorCheck",
    "Tenant",
    "utcnow",
    # New
    "AuditEvent",
    "TempArtifactRecord",
    "WorkflowJob",
    "WorkflowStep",
]
