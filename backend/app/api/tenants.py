"""Tenant CRUD + setup trigger endpoints."""

import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Domain, Mailbox, Tenant
from app.services.encryption import encrypt, decrypt

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"], dependencies=[Depends(check_auth)])


# ── Schemas ──────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str
    admin_email: EmailStr
    admin_password: str
    new_password: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        if len(v) > 200:
            raise ValueError("Name too long (max 200 chars)")
        return v

    @field_validator("admin_password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("Password cannot be empty")
        return v


class TenantOut(BaseModel):
    id: str
    name: str
    admin_email: str
    status: str
    current_step: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    completed_at: str | None

    model_config = {"from_attributes": True}


class TenantDetail(TenantOut):
    tenant_id_ms: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    cert_password: str | None = None
    mfa_secret: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────

def _tenant_to_out(t: Tenant) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "admin_email": t.admin_email,
        "status": t.status,
        "current_step": t.current_step,
        "error_message": t.error_message,
        "step_results": t.step_results,
        "health_results": t.health_results,
        "last_health_check": t.last_health_check.isoformat() if t.last_health_check else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


def _decrypt_safe(val: bytes | None) -> str | None:
    if val is None:
        return None
    try:
        return decrypt(val)
    except Exception:
        return None


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("")
async def list_tenants(
    status_filter: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    valid_statuses = {"pending", "queued", "running", "complete", "failed"}
    if status_filter and status_filter not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status filter. Valid: {', '.join(valid_statuses)}")

    # Subquery for mailbox count per tenant
    mailbox_count_sq = (
        select(Mailbox.tenant_id, func.count().label("mailbox_count"))
        .group_by(Mailbox.tenant_id)
        .subquery()
    )

    query = (
        select(Tenant, mailbox_count_sq.c.mailbox_count)
        .outerjoin(mailbox_count_sq, Tenant.id == mailbox_count_sq.c.tenant_id)
        .order_by(Tenant.created_at.desc())
    )
    if status_filter:
        query = query.where(Tenant.status == status_filter)

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.all()

    # Count total
    count_q = select(func.count()).select_from(Tenant)
    if status_filter:
        count_q = count_q.where(Tenant.status == status_filter)
    count_result = await db.execute(count_q)
    total = count_result.scalar()

    # Fetch domains for all tenants on this page
    tenant_ids = [t.id for t, _ in rows]
    domain_map: dict[uuid.UUID, list[dict]] = {}
    if tenant_ids:
        domain_q = select(Domain).where(Domain.tenant_id.in_(tenant_ids))
        domain_result = await db.execute(domain_q)
        for d in domain_result.scalars().all():
            domain_map.setdefault(d.tenant_id, []).append({
                "domain": d.domain,
                "is_verified": d.is_verified,
                "dkim_enabled": d.dkim_enabled,
            })

    tenants_out = []
    for tenant, mb_count in rows:
        out = _tenant_to_out(tenant)
        out["mailbox_count"] = mb_count or 0
        out["domains"] = domain_map.get(tenant.id, [])
        tenants_out.append(out)

    return {
        "tenants": tenants_out,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("", status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    # Check for duplicate
    existing = await db.execute(select(Tenant).where(Tenant.admin_email == body.admin_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant with this email already exists")

    tenant = Tenant(
        name=body.name,
        admin_email=body.admin_email,
        admin_password=encrypt(body.admin_password),
        new_password=encrypt(body.new_password) if body.new_password else None,
        status="pending",
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return _tenant_to_out(tenant)


@router.post("/bulk", status_code=201)
async def bulk_create_tenants(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Accept CSV or JSON file with tenant data."""
    content = await file.read()
    text = content.decode("utf-8-sig")

    tenants_data = []
    if file.filename and file.filename.endswith(".json"):
        tenants_data = json.loads(text)
    else:
        # CSV: expect columns email, password, [new_password], [name]
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            email = row.get("email", "").strip()
            password = row.get("password", "").strip()
            if email and password:
                tenants_data.append({
                    "admin_email": email,
                    "admin_password": password,
                    "new_password": row.get("new_password", "").strip() or None,
                    "name": row.get("name", "").strip() or email.split("@")[1].split(".")[0],
                })

    created = []
    skipped = []
    for td in tenants_data:
        existing = await db.execute(select(Tenant).where(Tenant.admin_email == td["admin_email"]))
        if existing.scalar_one_or_none():
            skipped.append(td["admin_email"])
            continue

        tenant = Tenant(
            name=td.get("name", td["admin_email"].split("@")[1].split(".")[0]),
            admin_email=td["admin_email"],
            admin_password=encrypt(td["admin_password"]),
            new_password=encrypt(td["new_password"]) if td.get("new_password") else None,
            status="pending",
        )
        db.add(tenant)
        created.append(td["admin_email"])

    await db.commit()
    return {"created": len(created), "skipped": len(skipped), "skipped_emails": skipped}


@router.get("/{tenant_id}/credentials")
async def download_credentials(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "admin_email": tenant.admin_email,
        "tenant_id": _decrypt_safe(tenant.tenant_id_ms),
        "client_id": _decrypt_safe(tenant.client_id),
        "client_secret": _decrypt_safe(tenant.client_secret),
        "cert_password": _decrypt_safe(tenant.cert_password),
        "mfa_secret": _decrypt_safe(tenant.mfa_secret),
    }


@router.post("/{tenant_id}/setup")
async def queue_setup(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status in ("running", "queued"):
        raise HTTPException(status_code=409, detail=f"Tenant is already {tenant.status}")

    from app.tasks.tenant_setup import run_tenant_setup
    tenant.status = "queued"
    tenant.error_message = None
    tenant.current_step = "Queued for setup"
    await db.commit()

    run_tenant_setup.delay(str(tenant.id))
    return {"status": "queued", "tenant_id": str(tenant.id)}


@router.post("/{tenant_id}/retry")
async def retry_setup(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status not in ("failed", "complete", "pending"):
        raise HTTPException(status_code=409, detail=f"Cannot retry tenant in status: {tenant.status}")

    from app.tasks.tenant_setup import run_tenant_setup
    tenant.status = "queued"
    tenant.error_message = None
    tenant.current_step = "Queued for retry"
    await db.commit()

    run_tenant_setup.delay(str(tenant.id))
    return {"status": "queued", "tenant_id": str(tenant.id)}


@router.post("/{tenant_id}/health-check")
async def health_check(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status != "complete":
        raise HTTPException(status_code=409, detail="Health check only available for completed tenants")

    from app.tasks.tenant_health import run_tenant_health_check
    run_tenant_health_check.delay(str(tenant.id))
    return {"status": "queued", "tenant_id": str(tenant.id)}


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    out = _tenant_to_out(tenant)
    out["tenant_id_ms"] = _decrypt_safe(tenant.tenant_id_ms)
    out["client_id"] = _decrypt_safe(tenant.client_id)
    out["client_secret"] = _decrypt_safe(tenant.client_secret)
    out["cert_password"] = _decrypt_safe(tenant.cert_password)
    out["mfa_secret"] = _decrypt_safe(tenant.mfa_secret)
    return out


class TenantUpdate(BaseModel):
    admin_password: str | None = None
    new_password: str | None = None


@router.patch("/{tenant_id}")
async def update_tenant(tenant_id: uuid.UUID, body: TenantUpdate, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status in ("running", "queued"):
        raise HTTPException(status_code=409, detail="Cannot edit tenant while setup is running")

    if body.admin_password is not None:
        tenant.admin_password = encrypt(body.admin_password)
    if body.new_password is not None:
        tenant.new_password = encrypt(body.new_password) if body.new_password else None

    tenant.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(tenant)
    return _tenant_to_out(tenant)


@router.delete("/{tenant_id}")
async def delete_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.delete(tenant)
    await db.commit()
    return {"status": "deleted"}
