"""Celery tasks: SMTP/DNS/blacklist health checks + Celery Beat scheduled tasks."""

import logging
import smtplib
import socket
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from datetime import timedelta

from app.config import settings
from app.models import Alert, Mailbox, MailboxJob, MonitorCheck, Tenant
from app.services.encryption import decrypt
from app.tasks.celery_app import celery_app
from app.websocket import publish_event_sync

logger = logging.getLogger(__name__)
sync_engine = create_engine(settings.database_url_sync)


def _save_check(tenant_id: str, mailbox_id: str | None, check_type: str,
                status: str, detail: str = None, response_ms: int = None):
    with Session(sync_engine) as db:
        db.add(MonitorCheck(
            tenant_id=tenant_id,
            mailbox_id=mailbox_id,
            check_type=check_type,
            status=status,
            detail=detail,
            response_ms=response_ms,
        ))
        # Update mailbox status
        if mailbox_id:
            mb = db.get(Mailbox, mailbox_id)
            if mb:
                mb.last_monitor_status = status
                mb.last_monitor_at = datetime.now(timezone.utc)
        db.commit()


def _create_alert(tenant_id: str, alert_type: str, severity: str, message: str):
    with Session(sync_engine) as db:
        db.add(Alert(
            tenant_id=tenant_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
        ))
        db.commit()

    publish_event_sync("alert", {
        "tenant_id": tenant_id,
        "alert_type": alert_type,
        "severity": severity,
        "message": message,
    })


def smtp_check(tenant_id: str, mailbox_id: str, email: str, password: str) -> str:
    """Test SMTP AUTH login for a mailbox."""
    start = time.time()
    try:
        server = smtplib.SMTP("smtp.office365.com", 587, timeout=15)
        server.starttls()
        server.login(email, password)
        server.quit()
        elapsed = int((time.time() - start) * 1000)
        _save_check(tenant_id, mailbox_id, "smtp_send", "healthy",
                     "SMTP login successful", elapsed)
        return "healthy"
    except smtplib.SMTPAuthenticationError as e:
        elapsed = int((time.time() - start) * 1000)
        detail = str(e)[:200]
        status = "auth_failed"
        if "5.7.139" in str(e) or "blocked" in str(e).lower():
            status = "blocked"
        _save_check(tenant_id, mailbox_id, "smtp_send", status, detail, elapsed)
        return status
    except (socket.timeout, smtplib.SMTPConnectError) as e:
        elapsed = int((time.time() - start) * 1000)
        _save_check(tenant_id, mailbox_id, "smtp_send", "timeout",
                     str(e)[:200], elapsed)
        return "timeout"
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        _save_check(tenant_id, mailbox_id, "smtp_send", "error",
                     str(e)[:200], elapsed)
        return "error"


def dns_check(tenant_id: str, domain: str) -> str:
    """Check MX and SPF records for a domain."""
    import subprocess
    try:
        # MX check
        result = subprocess.run(
            ["dig", "+short", "MX", domain],
            capture_output=True, text=True, timeout=10,
        )
        mx_records = result.stdout.strip()
        has_mx = "mail.protection.outlook.com" in mx_records

        # SPF check
        result = subprocess.run(
            ["dig", "+short", "TXT", domain],
            capture_output=True, text=True, timeout=10,
        )
        has_spf = "spf.protection.outlook.com" in result.stdout

        if has_mx and has_spf:
            status = "healthy"
            detail = f"MX: {mx_records[:100]}"
        elif has_mx:
            status = "warning"
            detail = "MX OK but SPF missing"
        else:
            status = "error"
            detail = "MX record missing"

        _save_check(tenant_id, None, "dns", status, detail)
        return status
    except Exception as e:
        _save_check(tenant_id, None, "dns", "error", str(e)[:200])
        return "error"


@celery_app.task(name="app.tasks.monitor.run_tenant_check", queue="monitor")
def run_tenant_check(tenant_id: str):
    """Run health checks for a specific tenant."""
    with Session(sync_engine) as db:
        tenant = db.get(Tenant, tenant_id)
        if not tenant or tenant.status != "complete":
            return

        # SMTP checks — sample up to 5 mailboxes
        mailboxes = db.execute(
            select(Mailbox).where(Mailbox.tenant_id == tenant_id, Mailbox.smtp_enabled == True)  # noqa: E712
            .limit(5)
        ).scalars().all()

        blocked_count = 0
        for mb in mailboxes:
            password = decrypt(mb.password) if mb.password else None
            if not password:
                continue
            result = smtp_check(str(tenant_id), str(mb.id), mb.email, password)
            if result == "blocked":
                blocked_count += 1

        if blocked_count > 0:
            _create_alert(str(tenant_id), "smtp_blocked", "critical",
                          f"{blocked_count} mailboxes blocked on tenant {tenant.name}")

        # DNS checks for domains
        from app.models import Domain
        domains = db.execute(
            select(Domain).where(Domain.tenant_id == tenant_id)
        ).scalars().all()
        for dom in domains:
            dns_check(str(tenant_id), dom.domain)


@celery_app.task(name="app.tasks.monitor.run_smtp_checks", queue="monitor")
def run_smtp_checks():
    """Celery Beat: run SMTP checks across all complete tenants."""
    with Session(sync_engine) as db:
        tenant_ids = [
            str(tid) for (tid,) in db.execute(
                select(Tenant.id).where(Tenant.status == "complete")
            ).all()
        ]

    for tid in tenant_ids:
        run_tenant_check.delay(tid)


@celery_app.task(name="app.tasks.monitor.run_dns_checks", queue="monitor")
def run_dns_checks():
    """Celery Beat: run DNS checks across all domains."""
    with Session(sync_engine) as db:
        from app.models import Domain
        domain_rows = [
            (str(row.tenant_id), row.domain) for row in db.execute(
                select(Domain.tenant_id, Domain.domain).where(Domain.is_verified == True)  # noqa: E712
            ).all()
        ]

    for tenant_id, domain in domain_rows:
        dns_check(tenant_id, domain)


# ── Stale task reaper ─────────────────────────────────────────────────────

STALE_TENANT_MINUTES = 15
STALE_JOB_MINUTES = 30


@celery_app.task(name="app.tasks.monitor.reap_stale_tasks", queue="monitor")
def reap_stale_tasks():
    """Mark tenants/jobs stuck in running/queued state as failed.

    Runs every 5 minutes via Celery Beat. If a tenant or mailbox job has been
    in running/queued state without an update for longer than the threshold,
    it's presumed dead (worker crashed, Docker stopped, etc.).
    """
    now = datetime.now(timezone.utc)
    tenant_cutoff = now - timedelta(minutes=STALE_TENANT_MINUTES)
    job_cutoff = now - timedelta(minutes=STALE_JOB_MINUTES)

    with Session(sync_engine) as db:
        # Stale tenants
        stale_tenants = db.execute(
            select(Tenant).where(
                Tenant.status.in_(["running", "queued"]),
                Tenant.updated_at < tenant_cutoff,
            )
        ).scalars().all()

        for tenant in stale_tenants:
            logger.warning(f"Reaping stale tenant: {tenant.name} (stuck since {tenant.updated_at})")
            tenant.status = "failed"
            tenant.error_message = (
                f"Task timed out — no progress for {STALE_TENANT_MINUTES} minutes. "
                f"Last step: {tenant.current_step or 'unknown'}"
            )
            tenant.current_step = None

            publish_event_sync("tenant_setup_progress", {
                "tenant_id": str(tenant.id),
                "step": 0,
                "total": 12,
                "message": f"Timed out: {tenant.error_message}",
                "status": "failed",
            })

        # Stale mailbox jobs
        stale_jobs = db.execute(
            select(MailboxJob).where(
                MailboxJob.status.in_(["running", "queued"]),
                MailboxJob.created_at < job_cutoff,
            )
        ).scalars().all()

        for job in stale_jobs:
            logger.warning(f"Reaping stale mailbox job: {job.id} (stuck since {job.created_at})")
            job.status = "failed"
            job.error_message = (
                f"Task timed out — no progress for {STALE_JOB_MINUTES} minutes. "
                f"Last phase: {job.current_phase or 'unknown'}"
            )

            publish_event_sync("mailbox_pipeline_progress", {
                "job_id": str(job.id),
                "step": 0,
                "total": 9,
                "message": f"Timed out: {job.error_message}",
                "status": "failed",
            })

        if stale_tenants or stale_jobs:
            db.commit()
            logger.info(f"Reaped {len(stale_tenants)} tenants, {len(stale_jobs)} jobs")
        else:
            logger.debug("No stale tasks found")
