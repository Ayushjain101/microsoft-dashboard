"""API v2 — Mailbox endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_auth
from app.database import get_db
from app.models import Mailbox
from app.schemas.mailbox import MailboxOut

router = APIRouter(prefix="/api/v2/mailboxes", tags=["mailboxes-v2"], dependencies=[Depends(check_auth)])


@router.get("/tenant/{tenant_id}", response_model=list[MailboxOut])
async def list_mailboxes(tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """List all mailboxes for a tenant."""
    result = await db.execute(
        select(Mailbox).where(Mailbox.tenant_id == tenant_id).order_by(Mailbox.created_at.desc())
    )
    return result.scalars().all()


@router.post("/{mailbox_id}/retry")
async def retry_mailbox(mailbox_id: UUID, db: AsyncSession = Depends(get_db)):
    """Retry provisioning for a single mailbox (placeholder for Phase 4 per-mailbox tracking)."""
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    mailbox = result.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    # TODO: Implement per-mailbox retry using provision_status
    return {"status": "not_implemented", "detail": "Per-mailbox retry will be available after provision_status migration"}
