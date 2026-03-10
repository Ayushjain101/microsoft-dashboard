"""API v2 — Settings endpoints — Cloudflare configs + alert webhook config."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import AppSetting, CloudflareConfig
from app.services.audit import log_audit
from app.services.encryption import decrypt, encrypt

router = APIRouter(prefix="/api/v2/settings", tags=["settings-v2"], dependencies=[Depends(check_auth)])


# ── Cloudflare Configs ───────────────────────────────────────────────────

class CFConfigCreate(BaseModel):
    label: str
    cf_email: str
    cf_api_key: str
    is_default: bool = False


class CFConfigOut(BaseModel):
    id: str
    label: str | None
    cf_email: str
    is_default: bool
    created_at: str


@router.get("/cloudflare")
async def list_cf_configs(db: AsyncSession = Depends(get_db)):
    """List all Cloudflare configurations."""
    result = await db.execute(select(CloudflareConfig).order_by(CloudflareConfig.created_at.desc()))
    configs = result.scalars().all()
    return {
        "configs": [
            {
                "id": str(c.id),
                "label": c.label,
                "cf_email": c.cf_email,
                "is_default": c.is_default,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in configs
        ]
    }


@router.post("/cloudflare", status_code=201)
async def create_cf_config(body: CFConfigCreate, db: AsyncSession = Depends(get_db)):
    """Create a new Cloudflare configuration."""
    if body.is_default:
        # Unset current defaults
        result = await db.execute(select(CloudflareConfig).where(CloudflareConfig.is_default == True))  # noqa: E712
        for c in result.scalars().all():
            c.is_default = False

    config = CloudflareConfig(
        label=body.label,
        cf_email=body.cf_email,
        cf_api_key=encrypt(body.cf_api_key),
        is_default=body.is_default,
    )
    db.add(config)
    await db.flush()
    await log_audit(db, "settings.cloudflare_created", payload={"label": body.label, "cf_email": body.cf_email})
    await db.commit()
    await db.refresh(config)
    return {
        "id": str(config.id),
        "label": config.label,
        "cf_email": config.cf_email,
        "is_default": config.is_default,
    }


@router.delete("/cloudflare/{config_id}")
async def delete_cf_config(config_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a Cloudflare configuration."""
    config = await db.get(CloudflareConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    label = config.label
    await db.delete(config)
    await log_audit(db, "settings.cloudflare_deleted", payload={"label": label, "config_id": str(config_id)})
    await db.commit()
    return {"status": "deleted"}


# ── Alert Settings ───────────────────────────────────────────────────────

class AlertSettingsUpdate(BaseModel):
    webhook_url: str | None = None
    smtp_check_interval_min: int | None = None
    dns_check_interval_hours: int | None = None


@router.get("/alerts")
async def get_alert_settings(db: AsyncSession = Depends(get_db)):
    """Get alert notification settings."""
    keys = ["webhook_url", "smtp_check_interval_min", "dns_check_interval_hours"]
    result = await db.execute(select(AppSetting).where(AppSetting.key.in_(keys)))
    settings_map = {s.key: s.value for s in result.scalars().all()}
    return settings_map


@router.put("/alerts")
async def update_alert_settings(body: AlertSettingsUpdate, db: AsyncSession = Depends(get_db)):
    """Update alert notification settings."""
    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    await log_audit(db, "settings.alerts_updated", payload=updates)
    await db.commit()
    return {"status": "updated"}
