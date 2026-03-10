"""API v2 — TOTP Vault — live authenticator codes for tenants with MFA secrets."""

import base64
import logging
import time
import uuid as uuid_mod

import pyotp
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Tenant
from app.services.audit import log_audit
from app.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/totp", tags=["totp-v2"], dependencies=[Depends(check_auth)])

TOTP_PERIOD = 30


class TOTPEntry(BaseModel):
    tenant_id: str
    tenant_name: str
    admin_email: str
    code: str
    remaining: int
    period: int


class SetSecretRequest(BaseModel):
    secret: str


def _compute_totp(secret: str) -> tuple[str, int]:
    """Return (code, seconds_remaining) for a TOTP secret."""
    totp = pyotp.TOTP(secret)
    code = totp.now()
    remaining = TOTP_PERIOD - int(time.time()) % TOTP_PERIOD
    return code, remaining


def _is_valid_base32(s: str) -> bool:
    """Check if a string is valid base32."""
    try:
        base64.b32decode(s.upper(), casefold=True)
        return True
    except Exception:
        return False


@router.get("", response_model=list[TOTPEntry])
async def list_totp(db: AsyncSession = Depends(get_db)):
    """List all tenants with MFA secrets and their live TOTP codes."""
    result = await db.execute(
        select(Tenant).where(Tenant.mfa_secret.isnot(None)).order_by(Tenant.name)
    )
    tenants = result.scalars().all()

    entries = []
    for t in tenants:
        try:
            secret = decrypt(t.mfa_secret)
            code, remaining = _compute_totp(secret)
            entries.append(
                TOTPEntry(
                    tenant_id=str(t.id),
                    tenant_name=t.name,
                    admin_email=t.admin_email,
                    code=code,
                    remaining=remaining,
                    period=TOTP_PERIOD,
                )
            )
        except Exception:
            logger.warning(f"Skipping tenant {t.id} ({t.name}) — corrupt/invalid MFA secret", exc_info=True)
            continue

    return entries


@router.get("/{tenant_id}", response_model=TOTPEntry)
async def get_totp(tenant_id: uuid_mod.UUID, db: AsyncSession = Depends(get_db)):
    """Get live TOTP code for a single tenant."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not tenant.mfa_secret:
        raise HTTPException(status_code=404, detail="No MFA secret stored for this tenant")

    secret = decrypt(tenant.mfa_secret)
    code, remaining = _compute_totp(secret)
    return TOTPEntry(
        tenant_id=str(tenant.id),
        tenant_name=tenant.name,
        admin_email=tenant.admin_email,
        code=code,
        remaining=remaining,
        period=TOTP_PERIOD,
    )


@router.put("/{tenant_id}/secret")
async def set_secret(tenant_id: uuid_mod.UUID, body: SetSecretRequest, db: AsyncSession = Depends(get_db)):
    """Manually set or update MFA secret for a tenant."""
    secret = body.secret.strip().replace(" ", "").upper()
    if not secret or not _is_valid_base32(secret):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base32 secret",
        )

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.mfa_secret = encrypt(secret)
    await log_audit(db, "totp.secret_set", tenant_id=tenant.id)
    await db.commit()
    return {"status": "ok", "tenant_id": str(tenant_id)}


@router.delete("/{tenant_id}/secret")
async def delete_secret(tenant_id: uuid_mod.UUID, db: AsyncSession = Depends(get_db)):
    """Remove MFA secret from a tenant."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.mfa_secret = None
    await log_audit(db, "totp.secret_deleted", tenant_id=tenant.id)
    await db.commit()
    return {"status": "ok", "tenant_id": str(tenant_id)}
