"""Celery tasks: SMTP/DNS/blacklist health checks + Celery Beat scheduled tasks."""

import json
import logging
import os
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
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True, pool_recycle=3600)


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
    """Test SMTP AUTH login for a mailbox (up to 2 attempts for transient errors)."""
    last_exc = None
    for attempt in range(2):
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
            # Deterministic — never retry
            elapsed = int((time.time() - start) * 1000)
            detail = str(e)[:200]
            status = "auth_failed"
            if "5.7.139" in str(e) or "blocked" in str(e).lower():
                status = "blocked"
            _save_check(tenant_id, mailbox_id, "smtp_send", status, detail, elapsed)
            return status
        except (socket.timeout, smtplib.SMTPConnectError, ConnectionError, OSError) as e:
            last_exc = e
            if attempt < 1:
                logger.warning(f"SMTP transient error for {email}, retrying in 3s: {e}")
                time.sleep(3)
                continue
            elapsed = int((time.time() - start) * 1000)
            _save_check(tenant_id, mailbox_id, "smtp_send", "timeout",
                         str(e)[:200], elapsed)
            return "timeout"
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            _save_check(tenant_id, mailbox_id, "smtp_send", "error",
                         str(e)[:200], elapsed)
            return "error"
    # Should not reach here, but just in case
    elapsed = int((time.time() - start) * 1000)
    _save_check(tenant_id, mailbox_id, "smtp_send", "error",
                 str(last_exc)[:200], elapsed)
    return "error"


def dns_check(tenant_id: str, domain: str) -> str:
    """Check MX and SPF records for a domain (up to 2 attempts for transient errors)."""
    import subprocess
    for attempt in range(2):
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
        except (subprocess.TimeoutExpired, OSError) as e:
            if attempt < 1:
                logger.warning(f"DNS transient error for {domain}, retrying in 2s: {e}")
                time.sleep(2)
                continue
            _save_check(tenant_id, None, "dns", "error", str(e)[:200])
            return "error"
        except Exception as e:
            _save_check(tenant_id, None, "dns", "error", str(e)[:200])
            return "error"
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
    """Mark tenants/jobs stuck in running/queued state as failed, and re-queue lost tasks.

    Runs every 5 minutes via Celery Beat. If a tenant or mailbox job has been
    in running/queued state without an update for longer than the threshold,
    it's presumed dead (worker crashed, connection lost, etc.).

    For "queued" tasks that never started (no current_step update), re-dispatches
    the Celery task instead of marking as failed, to recover from lost messages.
    """
    from app.tasks.tenant_setup import run_tenant_setup
    from app.tasks.mailbox_pipeline import run_mailbox_pipeline

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

        requeued_tenants = 0
        for tenant in stale_tenants:
            # If still "queued" with no progress, the Celery message was likely lost — re-dispatch
            if tenant.status == "queued":
                logger.warning(f"Re-queuing lost tenant task: {tenant.name}")
                tenant.updated_at = now
                db.commit()
                try:
                    run_tenant_setup.delay(str(tenant.id))
                    requeued_tenants += 1
                    continue
                except Exception:
                    logger.exception(f"Failed to re-queue tenant {tenant.name}")

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
                MailboxJob.updated_at < job_cutoff,
            )
        ).scalars().all()

        requeued_jobs = 0
        for job in stale_jobs:
            if job.status == "queued":
                logger.warning(f"Re-queuing lost mailbox job: {job.id}")
                job.updated_at = now
                db.commit()
                try:
                    run_mailbox_pipeline.delay(str(job.id))
                    requeued_jobs += 1
                    continue
                except Exception:
                    logger.exception(f"Failed to re-queue job {job.id}")

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
            logger.info(
                f"Reaped {len(stale_tenants) - requeued_tenants} tenants, "
                f"{len(stale_jobs) - requeued_jobs} jobs. "
                f"Re-queued {requeued_tenants} tenants, {requeued_jobs} jobs."
            )
        else:
            logger.debug("No stale tasks found")


# ── Mailflow monitoring ──────────────────────────────────────────────────

def _parse_mailflow_output(stdout: str) -> dict:
    """Extract JSON result from PowerShell stdout (banner text may precede it)."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"total": 0, "statuses": {}}


@celery_app.task(name="app.tasks.monitor.run_mailflow_check")
def run_mailflow_check(tenant_id: str):
    """Run Get-MessageTrace for a tenant and save results. Runs on selenium server."""
    from app.tasks.mailbox_pipeline import _load_tenant_data
    from app.services.powershell import PowerShellRunner, check_pwsh_available

    if not check_pwsh_available():
        logger.warning("pwsh not available, skipping mailflow check")
        return

    tenant_data = _load_tenant_data(tenant_id)
    pfx_path = tenant_data.get("cert_pfx_path")

    if not tenant_data.get("client_id") or not tenant_data.get("org_domain"):
        logger.warning(f"Tenant {tenant_id} missing app registration, skipping mailflow")
        return

    try:
        ps = PowerShellRunner(tenant_data)
        commands = [
            "$end = Get-Date",
            "$start = $end.AddHours(-24)",
            "$traces = Get-MessageTraceV2 -StartDate $start -EndDate $end -PageSize 5000",
            "$summary = $traces | Group-Object Status | Select-Object Name, Count",
            "$total = ($traces | Measure-Object).Count",
            "$result = @{ total = $total; statuses = @{} }",
            "foreach ($s in $summary) { $result.statuses[$s.Name] = $s.Count }",
            "$result | ConvertTo-Json -Compress",
        ]
        # Retry once on transient PowerShell errors
        try:
            stdout, stderr = ps.run(commands, timeout=120)
        except RuntimeError as e:
            logger.warning(f"Mailflow PowerShell transient error for {tenant_id}, retrying in 10s: {e}")
            time.sleep(10)
            ps = PowerShellRunner(tenant_data)
            stdout, stderr = ps.run(commands, timeout=120)
        result = _parse_mailflow_output(stdout)

        total = result.get("total", 0)
        statuses = result.get("statuses", {})
        failed = statuses.get("Failed", 0) + statuses.get("FilteredAsSpam", 0)

        if total > 0:
            fail_pct = failed / total
            if fail_pct > 0.3:
                status = "critical"
            elif fail_pct > 0.1:
                status = "warning"
            else:
                status = "healthy"
        else:
            status = "warning"

        _save_check(tenant_id, None, "mailflow", status, json.dumps(result))

        if status == "critical":
            _create_alert(tenant_id, "mailflow_degraded", "critical",
                          f"Mailflow degraded: {failed}/{total} messages failed/spam "
                          f"({int(failed/total*100)}%) in last 24h")
        elif total == 0:
            _create_alert(tenant_id, "mailflow_idle", "warning",
                          f"No messages traced in last 24h for tenant {tenant_data['tenant_name']}")

        logger.info(f"Mailflow check for {tenant_id}: {status} (total={total}, failed={failed})")

    except Exception as e:
        logger.exception(f"Mailflow check failed for {tenant_id}")
        _save_check(tenant_id, None, "mailflow", "error", str(e)[:500])
    finally:
        if pfx_path and os.path.exists(pfx_path):
            os.unlink(pfx_path)


@celery_app.task(name="app.tasks.monitor.run_mailflow_checks", queue="monitor")
def run_mailflow_checks():
    """Celery Beat: dispatch mailflow checks for all complete tenants."""
    with Session(sync_engine) as db:
        tenant_ids = [
            str(tid) for (tid,) in db.execute(
                select(Tenant.id).where(Tenant.status == "complete")
            ).all()
        ]

    for i, tid in enumerate(tenant_ids):
        run_mailflow_check.apply_async(args=[tid], countdown=i * 30)

    logger.info(f"Dispatched {len(tenant_ids)} mailflow checks")
