"""Mailbox schemas for API v2."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class MailboxOut(BaseModel):
    id: UUID
    tenant_id: UUID
    display_name: str | None = None
    email: str
    smtp_enabled: bool = False
    provision_status: str | None = None
    last_monitor_status: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MailboxCreateRequest(BaseModel):
    domain: str
    mailbox_count: int = 50
    cf_email: str | None = None
    cf_api_key: str | None = None
    custom_names: list[str] | None = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if "." not in v or len(v) > 253:
            raise ValueError("Invalid domain format")
        return v

    @field_validator("mailbox_count")
    @classmethod
    def validate_count(cls, v: int) -> int:
        if v < 1 or v > 500:
            raise ValueError("mailbox_count must be between 1 and 500")
        return v

    @field_validator("custom_names")
    @classmethod
    def validate_names(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            for name in v:
                parts = name.strip().split()
                if len(parts) < 2:
                    raise ValueError(f"Each name must have first and last name: '{name}'")
        return v
