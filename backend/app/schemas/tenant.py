"""Tenant schemas for API v2."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class TenantOut(BaseModel):
    id: UUID
    name: str
    admin_email: str
    status: str
    current_step: str | None = None
    error_message: str | None = None
    step_results: dict | None = None
    health_results: dict | None = None
    last_health_check: datetime | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class TenantCreate(BaseModel):
    name: str
    admin_email: EmailStr
    admin_password: str
    new_password: str | None = None

    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 200:
            raise ValueError("Name must be 1-200 characters")
        return v
