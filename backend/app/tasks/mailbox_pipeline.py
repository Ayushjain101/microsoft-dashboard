"""Celery task: 9-step mailbox creation pipeline.

Inlines all steps from api-scripts/steps/ into one Celery task.
Steps: assign-license, enable-org-smtp, add-domain, verify-domain,
       setup-dkim, setup-dmarc, create-mailboxes, enable-smtp,
       disable-calendar-processing
"""

import logging
import os
import tempfile
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models import Domain, Mailbox, MailboxJob, Tenant
from app.services.encryption import decrypt, decrypt_bytes, encrypt
from app.tasks.celery_app import celery_app
from app.websocket import publish_event_sync

logger = logging.getLogger(__name__)
sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True, pool_recycle=3600)

STEPS = [
    "Assign License", "Enable Org SMTP", "Add Domain", "Verify Domain",
    "Setup DKIM", "Setup DMARC", "Create Mailboxes", "Enable SMTP",
    "Disable Calendar Processing",
]


def _publish_progress(job_id: str, step: int, message: str, status: str = "running"):
    publish_event_sync("mailbox_pipeline_progress", {
        "job_id": job_id, "step": step, "total": len(STEPS),
        "message": message, "status": status,
    })
    with Session(sync_engine) as db:
        job = db.get(MailboxJob, job_id)
        if job:
            job.status = status
            job.current_phase = f"Step {step}/{len(STEPS)}: {message}"
            db.commit()


def _record_step_result(job_id: str, step: int, status: str, detail: str | None = None):
    """Record per-step result in the job's step_results JSON column."""
    with Session(sync_engine) as db:
        job = db.get(MailboxJob, job_id)
        if not job:
            return
        results = job.step_results or {}
        entry = {"status": status, "message": STEPS[step - 1]}
        if detail:
            entry["detail"] = detail
        results[str(step)] = entry
        job.step_results = results
        flag_modified(job, "step_results")
        db.commit()

    publish_event_sync("mailbox_step_result", {
        "job_id": job_id, "step": step, "step_status": status,
        "message": STEPS[step - 1], "detail": detail,
    })


def _load_tenant_data(tenant_id: str) -> dict:
    """Load decrypted tenant credentials from DB."""
    with Session(sync_engine) as db:
        tenant = db.get(Tenant, tenant_id)
        if not tenant:
            raise RuntimeError(f"Tenant {tenant_id} not found")

        data = {
            "tenant_name": tenant.name,
            "tenant_id": decrypt(tenant.tenant_id_ms) if tenant.tenant_id_ms else None,
            "client_id": decrypt(tenant.client_id) if tenant.client_id else None,
            "client_secret": decrypt(tenant.client_secret) if tenant.client_secret else None,
            "cert_password": decrypt(tenant.cert_password) if tenant.cert_password else None,
            "admin_email": tenant.admin_email,
            "admin_password": decrypt(tenant.admin_password) if tenant.admin_password else None,
        }

        # Write PFX to temp file if available
        if tenant.cert_pfx:
            pfx_bytes = decrypt_bytes(tenant.cert_pfx)
            fd, pfx_path = tempfile.mkstemp(suffix=".pfx")
            with os.fdopen(fd, "wb") as f:
                f.write(pfx_bytes)
            data["cert_pfx_path"] = pfx_path
        else:
            data["cert_pfx_path"] = None

        # Resolve org_domain
        if data["tenant_id"] and data["client_id"] and data["client_secret"]:
            from app.services.graph_client import MicrosoftGraphClient
            try:
                g = MicrosoftGraphClient(data["tenant_id"], data["client_id"], data["client_secret"])
                resp = g.get("/organization?$select=verifiedDomains")
                for org in resp.json().get("value", []):
                    for d in org.get("verifiedDomains", []):
                        if d.get("isInitial") and d["name"].endswith(".onmicrosoft.com"):
                            data["org_domain"] = d["name"]
                            break
            except Exception:
                pass
        if "org_domain" not in data:
            data["org_domain"] = f"{tenant.name}.onmicrosoft.com"

        return data


@celery_app.task(name="app.tasks.mailbox_pipeline.run_mailbox_pipeline", bind=True, queue="mailbox",
                 acks_late=True, reject_on_worker_lost=True)
def run_mailbox_pipeline(self, job_id: str):
    """Run the 9-step mailbox pipeline."""

    with Session(sync_engine) as db:
        job = db.get(MailboxJob, job_id)
        if not job:
            return {"status": "error", "reason": "job_not_found"}

        # Idempotency: skip if already completed or stopped
        if job.status in ("complete", "stopped"):
            logger.info(f"Job {job_id} already {job.status}, skipping")
            return {"status": job.status, "reason": "already_finished"}

        tenant_id = str(job.tenant_id)
        domain = job.domain
        mailbox_count = job.mailbox_count
        cf_email = job.cf_email
        cf_api_key = decrypt(job.cf_api_key) if job.cf_api_key else None

        job.status = "running"
        job.step_results = {}
        db.commit()

    pfx_path = None
    current_step = 0

    try:
        tenant_data = _load_tenant_data(tenant_id)
        pfx_path = tenant_data.get("cert_pfx_path")

        from app.services.graph_client import MicrosoftGraphClient
        from app.services.cloudflare_client import CloudflareClient
        from app.services.powershell import PowerShellRunner, check_pwsh_available, ensure_exchange_module
        from app.services.name_generator import generate_mailbox_identities

        graph = MicrosoftGraphClient(
            tenant_data["tenant_id"], tenant_data["client_id"], tenant_data["client_secret"]
        )

        # Resolve CF credentials (use job-specific or default from DB)
        if not cf_email or not cf_api_key:
            with Session(sync_engine) as db:
                from app.models import CloudflareConfig
                result = db.execute(
                    select(CloudflareConfig).where(CloudflareConfig.is_default == True)  # noqa: E712
                )
                cf_config = result.scalar_one_or_none()
                if cf_config:
                    cf_email = cf_config.cf_email
                    cf_api_key = decrypt(cf_config.cf_api_key)

        if not cf_email or not cf_api_key:
            raise RuntimeError("No Cloudflare credentials available (job or default)")

        cf = CloudflareClient(api_key=cf_api_key, email=cf_email)

        # ── Step 1: Assign License ──────────────────────────────
        current_step = 1
        _publish_progress(job_id, 1, "Assign License")
        try:
            resp = graph.get("/subscribedSkus")
            skus = resp.json().get("value", [])
            target_sku = None
            for sku in skus:
                available = sku.get("prepaidUnits", {}).get("enabled", 0) - sku.get("consumedUnits", 0)
                if available > 0:
                    target_sku = sku
                    break
            if target_sku:
                resp = graph.get("/users?$select=id,userPrincipalName&$top=1")
                users = resp.json().get("value", [])
                if users:
                    user_id = users[0]["id"]
                    resp = graph.get(f"/users/{user_id}/licenseDetails")
                    existing = [ld["skuId"] for ld in resp.json().get("value", [])]
                    if target_sku["skuId"] not in existing:
                        graph.post(f"/users/{user_id}/assignLicense", {
                            "addLicenses": [{"skuId": target_sku["skuId"], "disabledPlans": []}],
                            "removeLicenses": [],
                        })
            _record_step_result(job_id, 1, "success")
        except Exception as e:
            _record_step_result(job_id, 1, "warning", str(e))
            logger.warning(f"Step 1 warning: {e}")

        # ── Step 2: Enable Org SMTP ─────────────────────────────
        current_step = 2
        _publish_progress(job_id, 2, "Enable Org SMTP")
        try:
            if check_pwsh_available():
                ps = PowerShellRunner(tenant_data)
                try:
                    ps.run(["Set-TransportConfig -SmtpClientAuthenticationDisabled $false"])
                except Exception:
                    try:
                        graph.patch("/admin/exchange/transportConfig", beta=True,
                                    json_data={"smtpAuthEnabled": True})
                    except Exception:
                        raise
            else:
                graph.patch("/admin/exchange/transportConfig", beta=True,
                            json_data={"smtpAuthEnabled": True})
            _record_step_result(job_id, 2, "success")
        except Exception as e:
            _record_step_result(job_id, 2, "warning", str(e))
            logger.warning(f"Step 2 warning: {e}")

        # ── Step 3: Add Domain ──────────────────────────────────
        current_step = 3
        _publish_progress(job_id, 3, "Add Domain")
        try:
            try:
                graph.post("/domains", {"id": domain})
            except RuntimeError as e:
                if "already exist" not in str(e).lower() and "409" not in str(e):
                    raise

            # Get verification records
            verification_records = []
            for attempt in range(5):
                try:
                    resp = graph.get(f"/domains/{domain}/verificationDnsRecords")
                    verification_records = resp.json().get("value", [])
                    break
                except RuntimeError:
                    time.sleep(attempt * 5 + 5)

            for rec in verification_records:
                if rec.get("recordType") == "Txt":
                    cf.upsert_dns_record(domain, "TXT", domain, rec.get("text", ""), proxied=False)

            mx_host = domain.replace(".", "-") + ".mail.protection.outlook.com"
            cf.upsert_dns_record(domain, "MX", domain, mx_host, priority=0, proxied=False)

            spf_value = "v=spf1 include:spf.protection.outlook.com -all"
            try:
                cf.create_dns_record(domain, "TXT", domain, spf_value, proxied=False)
            except RuntimeError:
                pass  # May already exist

            cf.upsert_dns_record(domain, "CNAME", f"autodiscover.{domain}",
                                 "autodiscover.outlook.com", proxied=False)
            _record_step_result(job_id, 3, "success")
        except Exception as e:
            _record_step_result(job_id, 3, "failed", str(e))
            raise

        # ── Step 4: Verify Domain ───────────────────────────────
        current_step = 4
        _publish_progress(job_id, 4, "Verify Domain")
        try:
            backoffs = [5, 15, 30, 60]
            verified = False
            for attempt, wait in enumerate(backoffs):
                try:
                    resp = graph.post(f"/domains/{domain}/verify")
                    if resp.json().get("isVerified"):
                        verified = True
                        break
                except RuntimeError:
                    pass
                time.sleep(wait)
            if not verified:
                # Final attempt
                try:
                    resp = graph.post(f"/domains/{domain}/verify")
                    verified = resp.json().get("isVerified", False)
                except RuntimeError:
                    pass
                if not verified:
                    raise RuntimeError(f"Domain '{domain}' could not be verified")

            # Save domain to DB
            with Session(sync_engine) as db:
                existing = db.execute(
                    select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
                ).scalar_one_or_none()
                if not existing:
                    db.add(Domain(tenant_id=tenant_id, domain=domain, is_verified=True))
                else:
                    existing.is_verified = True
                db.commit()
            _record_step_result(job_id, 4, "success")
        except Exception as e:
            _record_step_result(job_id, 4, "failed", str(e))
            raise

        # ── Step 5: Setup DKIM ──────────────────────────────────
        current_step = 5
        _publish_progress(job_id, 5, "Setup DKIM")
        dkim_ok = False
        try:
            org_domain = tenant_data["org_domain"]
            domain_dashed = domain.replace(".", "-")
            for selector in ["selector1", "selector2"]:
                cname_name = f"{selector}._domainkey.{domain}"
                cname_target = f"{selector}-{domain_dashed}._domainkey.{org_domain}"
                cf.upsert_dns_record(domain, "CNAME", cname_name, cname_target, proxied=False)

            if check_pwsh_available():
                ps = PowerShellRunner(tenant_data)
                try:
                    ps.run([f"New-DkimSigningConfig -DomainName '{domain}' -Enabled $true"])
                    dkim_ok = True
                except RuntimeError as e:
                    if "already exists" in str(e).lower():
                        try:
                            ps.run([f"Set-DkimSigningConfig -Identity '{domain}' -Enabled $true"])
                            dkim_ok = True
                        except RuntimeError:
                            pass

            with Session(sync_engine) as db:
                dom = db.execute(
                    select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
                ).scalar_one_or_none()
                if dom and dkim_ok:
                    dom.dkim_enabled = True
                    db.commit()

            if dkim_ok:
                _record_step_result(job_id, 5, "success")
            else:
                _record_step_result(job_id, 5, "warning", "DKIM signing config not enabled — Microsoft may need more time to provision. Use the DKIM button to retry later.")
        except Exception as e:
            _record_step_result(job_id, 5, "warning", str(e))
            logger.warning(f"Step 5 DKIM warning: {e}")

        # ── Step 6: Setup DMARC ─────────────────────────────────
        current_step = 6
        _publish_progress(job_id, 6, "Setup DMARC")
        try:
            dmarc_value = f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}"
            cf.upsert_dns_record(domain, "TXT", f"_dmarc.{domain}", dmarc_value, proxied=False)

            with Session(sync_engine) as db:
                dom = db.execute(
                    select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
                ).scalar_one_or_none()
                if dom:
                    dom.dmarc_created = True
                    db.commit()
            _record_step_result(job_id, 6, "success")
        except Exception as e:
            _record_step_result(job_id, 6, "warning", str(e))
            logger.warning(f"Step 6 DMARC warning: {e}")

        # ── Step 7: Create Mailboxes ────────────────────────────
        current_step = 7
        _publish_progress(job_id, 7, "Create Mailboxes")
        try:
            if not check_pwsh_available():
                raise RuntimeError("PowerShell (pwsh) not available")
            ensure_exchange_module()

            identities = generate_mailbox_identities(mailbox_count, domain, tenant_data["tenant_name"])
            ps = PowerShellRunner(tenant_data)

            from app.services.powershell import escape_ps_string

            commands = []
            for mb in identities:
                safe_pwd = escape_ps_string(mb["password"])
                safe_name = escape_ps_string(mb["display_name"])
                safe_alias = escape_ps_string(mb["alias"])
                commands.append(
                    f"$pwd = ConvertTo-SecureString '{safe_pwd}' -AsPlainText -Force; "
                    f"try {{ "
                    f"New-Mailbox -Room -Name '{safe_name}' "
                    f"-Alias '{safe_alias}' "
                    f"-PrimarySmtpAddress '{mb['email']}' "
                    f"-EnableRoomMailboxAccount $true "
                    f"-MicrosoftOnlineServicesID '{mb['email']}' "
                    f"-RoomMailboxPassword $pwd; "
                    f"Write-Host 'CREATED: {mb['email']}' "
                    f"}} catch {{ "
                    f"if ($_.Exception.Message -like '*already exists*' -or "
                    f"$_.Exception.Message -like '*proxy address*already being used*') {{ "
                    f"Write-Host 'EXISTS: {mb['email']}' "
                    f"}} else {{ "
                    f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
                    f"}} }}"
                )

            stdout, _ = ps.run_batched(commands, batch_size=10, timeout=600)

            # Parse results and save to DB
            with Session(sync_engine) as db:
                dom = db.execute(
                    select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
                ).scalar_one_or_none()
                domain_id = dom.id if dom else None

                for mb in identities:
                    existing = db.execute(
                        select(Mailbox).where(Mailbox.email == mb["email"])
                    ).scalar_one_or_none()
                    if not existing:
                        db.add(Mailbox(
                            tenant_id=tenant_id,
                            domain_id=domain_id,
                            display_name=mb["display_name"],
                            email=mb["email"],
                            password=encrypt(mb["password"]),
                        ))
                db.commit()
            _record_step_result(job_id, 7, "success")
        except Exception as e:
            _record_step_result(job_id, 7, "failed", str(e))
            raise

        # ── Step 8: Enable SMTP ─────────────────────────────────
        current_step = 8
        _publish_progress(job_id, 8, "Enable SMTP")
        try:
            smtp_commands = []
            for mb in identities:
                smtp_commands.append(
                    f"try {{ "
                    f"Set-CASMailbox -Identity '{mb['email']}' -SmtpClientAuthenticationDisabled $false; "
                    f"Write-Host 'ENABLED: {mb['email']}' "
                    f"}} catch {{ "
                    f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
                    f"}}"
                )
            ps.run_batched(smtp_commands, batch_size=10, timeout=600)

            with Session(sync_engine) as db:
                for mb in identities:
                    existing = db.execute(
                        select(Mailbox).where(Mailbox.email == mb["email"])
                    ).scalar_one_or_none()
                    if existing:
                        existing.smtp_enabled = True
                db.commit()
            _record_step_result(job_id, 8, "success")
        except Exception as e:
            _record_step_result(job_id, 8, "warning", str(e))
            logger.warning(f"Step 8 SMTP warning: {e}")

        # ── Step 9: Disable Calendar Processing ─────────────────
        current_step = 9
        _publish_progress(job_id, 9, "Disable Calendar Processing")
        try:
            cal_commands = []
            for mb in identities:
                cal_commands.append(
                    f"try {{ "
                    f"Set-CalendarProcessing -Identity '{mb['email']}' "
                    f"-AutomateProcessing None -DeleteComments $false -DeleteSubject $false; "
                    f"Write-Host 'CONFIGURED: {mb['email']}' "
                    f"}} catch {{ "
                    f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
                    f"}}"
                )
            ps.run_batched(cal_commands, batch_size=10, timeout=600)
            _record_step_result(job_id, 9, "success")
        except Exception as e:
            _record_step_result(job_id, 9, "warning", str(e))
            logger.warning(f"Step 9 calendar warning: {e}")

        # ── Complete ────────────────────────────────────────────
        with Session(sync_engine) as db:
            job = db.get(MailboxJob, job_id)
            if job:
                job.status = "complete"
                job.current_phase = None
                job.completed_at = datetime.now(timezone.utc)
                db.commit()

        _publish_progress(job_id, len(STEPS), "Pipeline complete", "complete")
        return {"status": "complete", "job_id": job_id}

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        # Mark current step as failed if not already recorded
        if current_step > 0:
            _record_step_result(job_id, current_step, "failed", str(e))

        with Session(sync_engine) as db:
            job = db.get(MailboxJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = error_msg[:2000]
                db.commit()

        _publish_progress(job_id, 0, f"Failed: {str(e)}", "failed")
        return {"status": "failed", "error": str(e)}
    finally:
        # Cleanup temp PFX file
        if pfx_path and os.path.exists(pfx_path):
            os.unlink(pfx_path)


@celery_app.task(name="app.tasks.mailbox_pipeline.enable_dkim_task", bind=True, queue="mailbox",
                 acks_late=True, reject_on_worker_lost=True)
def enable_dkim_task(self, job_id: str):
    """Retry enabling DKIM for a completed mailbox job."""
    pfx_path = None
    try:
        with Session(sync_engine) as db:
            job = db.get(MailboxJob, job_id)
            if not job:
                return {"status": "error", "reason": "job_not_found"}

            tenant_id = str(job.tenant_id)
            domain = job.domain

        tenant_data = _load_tenant_data(tenant_id)
        pfx_path = tenant_data.get("cert_pfx_path")

        from app.services.powershell import PowerShellRunner, check_pwsh_available
        if not check_pwsh_available():
            raise RuntimeError("PowerShell (pwsh) not available")

        ps = PowerShellRunner(tenant_data)
        try:
            ps.run([f"Set-DkimSigningConfig -Identity '{domain}' -Enabled $true"])
        except RuntimeError as e:
            if "does not exist" in str(e).lower() or "couldn't find" in str(e).lower():
                ps.run([f"New-DkimSigningConfig -DomainName '{domain}' -Enabled $true"])
            else:
                raise

        with Session(sync_engine) as db:
            dom = db.execute(
                select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
            ).scalar_one_or_none()
            if dom:
                dom.dkim_enabled = True
                db.commit()

        publish_event_sync("dkim_enabled", {
            "job_id": job_id, "domain": domain, "success": True,
        })
        return {"status": "success", "domain": domain}

    except Exception as e:
        publish_event_sync("dkim_enabled", {
            "job_id": job_id, "success": False, "error": str(e),
        })
        return {"status": "failed", "error": str(e)}
    finally:
        if pfx_path and os.path.exists(pfx_path):
            os.unlink(pfx_path)
