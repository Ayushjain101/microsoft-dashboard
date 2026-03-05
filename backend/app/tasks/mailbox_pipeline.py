"""Celery task: 9-step mailbox creation pipeline.

Inlines all steps from api-scripts/steps/ into one Celery task.
Steps: assign-license, enable-org-smtp, add-domain, verify-domain,
       setup-dkim, setup-dmarc, create-mailboxes, enable-smtp,
       disable-calendar-processing
"""

import logging
import os
import smtplib
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


def _parse_ps_markers(stdout: str, success_markers: list[str], fail_marker: str = "FAILED:"):
    """Parse PowerShell stdout for success/failure markers.

    Returns (succeeded: dict[marker -> set[email]], failed: list[tuple[email, reason]])
    """
    succeeded: dict[str, set[str]] = {m: set() for m in success_markers}
    failed: list[tuple[str, str]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        for marker in success_markers:
            if line.startswith(marker):
                email = line[len(marker):].strip()
                succeeded[marker].add(email.lower())
                break
        else:
            if line.startswith(fail_marker):
                rest = line[len(fail_marker):].strip()
                parts = rest.split(" - ", 1)
                email = parts[0].strip().lower()
                reason = parts[1].strip() if len(parts) > 1 else "Unknown error"
                failed.append((email, reason))
    return succeeded, failed

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
        custom_names = job.custom_names
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
        from app.services.name_generator import generate_mailbox_identities, generate_custom_identities

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

            if custom_names:
                identities = generate_custom_identities(custom_names, mailbox_count, domain, tenant_data["tenant_name"])
            else:
                identities = generate_mailbox_identities(mailbox_count, domain, tenant_data["tenant_name"])
            ps = PowerShellRunner(tenant_data)

            from app.services.powershell import escape_ps_string

            # Wait for Exchange to accept the domain (propagation delay after Azure AD verification)
            domain_accepted = False
            for wait in [0, 10, 20, 30, 60, 60]:
                if wait:
                    logger.info(f"Waiting {wait}s for Exchange to accept domain {domain}...")
                    time.sleep(wait)
                try:
                    check_out, _ = ps.run([
                        f"Get-AcceptedDomain -Identity '{domain}' | Select-Object -ExpandProperty DomainName"
                    ])
                    if domain.lower() in check_out.lower():
                        domain_accepted = True
                        break
                except RuntimeError:
                    pass
            if not domain_accepted:
                logger.warning(f"Domain {domain} not yet in Exchange accepted domains, proceeding anyway")

            # Use domain tag in Name/Alias to avoid conflicts when multiple domains share a tenant
            domain_tag = domain.split(".")[0]

            commands = []
            for mb in identities:
                safe_pwd = escape_ps_string(mb["password"])
                # -Name must be unique in Exchange; for custom names many aliases share a display_name
                # so use alias in Name. -DisplayName shows the real person name.
                name_label = mb['alias'] if custom_names else mb['display_name']
                unique_name = escape_ps_string(f"{name_label} ({domain_tag})")
                safe_display = escape_ps_string(mb['display_name'])
                safe_alias = escape_ps_string(f"{mb['alias']}-{domain_tag}")
                commands.append(
                    f"$pwd = ConvertTo-SecureString '{safe_pwd}' -AsPlainText -Force; "
                    f"try {{ "
                    f"New-Mailbox -Room -Name '{unique_name}' "
                    f"-DisplayName '{safe_display}' "
                    f"-Alias '{safe_alias}' "
                    f"-PrimarySmtpAddress '{mb['email']}' "
                    f"-EnableRoomMailboxAccount $true "
                    f"-MicrosoftOnlineServicesID '{mb['email']}' "
                    f"-RoomMailboxPassword $pwd; "
                    f"Write-Host 'CREATED: {mb['email']}' "
                    f"}} catch {{ "
                    f"if ($_.Exception.Message -like '*already exists*' -or "
                    f"$_.Exception.Message -like '*proxy address*already being used*' -or "
                    f"$_.Exception.Message -like '*name*already being used*') {{ "
                    f"Write-Host 'EXISTS: {mb['email']}' "
                    f"}} else {{ "
                    f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
                    f"}} }}"
                )

            stdout, _ = ps.run_batched(commands, batch_size=10, timeout=600)

            # If many failures are due to domain not accepted, retry once after waiting
            succeeded_first, failed_first = _parse_ps_markers(stdout, ["CREATED:", "EXISTS:"])
            domain_reject_failures = [
                (email, reason) for email, reason in failed_first
                if "not an accepted domain" in reason.lower()
            ]
            if domain_reject_failures and len(domain_reject_failures) >= len(failed_first) * 0.5:
                logger.info(f"{len(domain_reject_failures)} mailboxes rejected due to domain not accepted, retrying after 60s...")
                time.sleep(60)
                # Rebuild commands only for failed emails
                failed_emails = {email.lower() for email, _ in domain_reject_failures}
                retry_commands = [cmd for cmd, mb in zip(commands, identities) if mb["email"].lower() in failed_emails]
                retry_stdout, _ = ps.run_batched(retry_commands, batch_size=10, timeout=600)
                # Merge results
                stdout = stdout + "\n" + retry_stdout

            # Parse PowerShell output markers (merged stdout includes retry output)
            succeeded, failed_list = _parse_ps_markers(stdout, ["CREATED:", "EXISTS:"])
            created_emails = succeeded["CREATED:"]
            exists_emails = succeeded["EXISTS:"]
            ok_emails = created_emails | exists_emails
            # Remove failures for emails that succeeded on retry
            failed_list = [(e, r) for e, r in failed_list if e.lower() not in ok_emails]

            # Only save mailboxes that actually succeeded
            with Session(sync_engine) as db:
                dom = db.execute(
                    select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
                ).scalar_one_or_none()
                domain_id = dom.id if dom else None

                for mb in identities:
                    if mb["email"].lower() not in ok_emails:
                        continue
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

            # Build step result detail
            detail = f"Created: {len(created_emails)}, Existed: {len(exists_emails)}, Failed: {len(failed_list)}"
            if failed_list:
                detail += "\n" + "\n".join(f"  {email} - {reason}" for email, reason in failed_list[:20])

            # Filter identities to only those that succeeded (for steps 8 & 9)
            identities = [mb for mb in identities if mb["email"].lower() in ok_emails]

            if len(ok_emails) == 0 and failed_list:
                _record_step_result(job_id, 7, "failed", detail)
                raise RuntimeError(f"All {len(failed_list)} mailboxes failed to create")
            elif failed_list:
                _record_step_result(job_id, 7, "warning", detail)
            else:
                _record_step_result(job_id, 7, "success", detail)
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
            smtp_stdout, _ = ps.run_batched(smtp_commands, batch_size=10, timeout=600)

            smtp_succeeded, smtp_failed = _parse_ps_markers(smtp_stdout, ["ENABLED:"])
            enabled_emails = smtp_succeeded["ENABLED:"]

            with Session(sync_engine) as db:
                for mb in identities:
                    if mb["email"].lower() not in enabled_emails:
                        continue
                    existing = db.execute(
                        select(Mailbox).where(Mailbox.email == mb["email"])
                    ).scalar_one_or_none()
                    if existing:
                        existing.smtp_enabled = True
                db.commit()

            smtp_detail = f"Enabled: {len(enabled_emails)}, Failed: {len(smtp_failed)}"
            if smtp_failed:
                smtp_detail += "\n" + "\n".join(f"  {email} - {reason}" for email, reason in smtp_failed[:20])

            if smtp_failed and not enabled_emails:
                _record_step_result(job_id, 8, "failed", smtp_detail)
            elif smtp_failed:
                _record_step_result(job_id, 8, "warning", smtp_detail)
            else:
                _record_step_result(job_id, 8, "success", smtp_detail)
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
            cal_stdout, _ = ps.run_batched(cal_commands, batch_size=10, timeout=600)

            cal_succeeded, cal_failed = _parse_ps_markers(cal_stdout, ["CONFIGURED:"])
            configured_emails = cal_succeeded["CONFIGURED:"]

            cal_detail = f"Configured: {len(configured_emails)}, Failed: {len(cal_failed)}"
            if cal_failed:
                cal_detail += "\n" + "\n".join(f"  {email} - {reason}" for email, reason in cal_failed[:20])

            if cal_failed and not configured_emails:
                _record_step_result(job_id, 9, "failed", cal_detail)
            elif cal_failed:
                _record_step_result(job_id, 9, "warning", cal_detail)
            else:
                _record_step_result(job_id, 9, "success", cal_detail)
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


def _update_dkim_step_result(job_id: str):
    """Update step 5 (Setup DKIM) from warning → success when DKIM is enabled later."""
    with Session(sync_engine) as db:
        job = db.get(MailboxJob, job_id)
        if not job or not job.step_results:
            return
        step5 = job.step_results.get("5")
        if step5 and step5.get("status") != "success":
            results = dict(job.step_results)
            results["5"] = {"status": "success", "message": "Setup DKIM"}
            job.step_results = results
            flag_modified(job, "step_results")
            db.commit()

    publish_event_sync("mailbox_step_result", {
        "job_id": job_id, "step": 5, "step_status": "success",
        "message": "Setup DKIM",
    })


@celery_app.task(name="app.tasks.mailbox_pipeline.enable_dkim_task", bind=True, queue="tenant_setup",
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
        err_lower_keywords = ["not exist", "couldn't be found", "couldn't find", "not found", "could not be found"]
        try:
            ps.run([f"Set-DkimSigningConfig -Identity '{domain}' -Enabled $true"])
        except RuntimeError as e:
            if any(kw in str(e).lower() for kw in err_lower_keywords):
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

        # Update step 5 in step_results from warning → success
        _update_dkim_step_result(job_id)

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


@celery_app.task(name="app.tasks.mailbox_pipeline.retry_pending_dkim", queue="tenant_setup")
def retry_pending_dkim():
    """Periodic task: retry DKIM enablement for all domains where dkim_enabled=False."""
    with Session(sync_engine) as db:
        domains = db.execute(
            select(Domain).where(Domain.dkim_enabled == False, Domain.is_verified == True)  # noqa: E712
        ).scalars().all()

        if not domains:
            return {"status": "no_pending"}

        results = []
        for dom in domains:
            tenant_id = str(dom.tenant_id)
            domain_name = dom.domain
            pfx_path = None
            try:
                tenant_data = _load_tenant_data(tenant_id)
                pfx_path = tenant_data.get("cert_pfx_path")

                from app.services.powershell import PowerShellRunner, check_pwsh_available
                if not check_pwsh_available():
                    results.append({"domain": domain_name, "status": "skipped", "reason": "no pwsh"})
                    continue

                ps = PowerShellRunner(tenant_data)
                err_keywords = ["not exist", "couldn't be found", "couldn't find", "not found", "could not be found"]
                try:
                    ps.run([f"Set-DkimSigningConfig -Identity '{domain_name}' -Enabled $true"])
                except RuntimeError as e:
                    if any(kw in str(e).lower() for kw in err_keywords):
                        ps.run([f"New-DkimSigningConfig -DomainName '{domain_name}' -Enabled $true"])
                    else:
                        raise

                dom.dkim_enabled = True
                db.commit()

                # Find the job for this domain and update step_results
                job = db.execute(
                    select(MailboxJob).where(
                        MailboxJob.tenant_id == dom.tenant_id,
                        MailboxJob.domain == domain_name,
                    )
                ).scalar_one_or_none()
                if job:
                    _update_dkim_step_result(str(job.id))

                results.append({"domain": domain_name, "status": "success"})
                logger.info(f"DKIM enabled for {domain_name}")

                publish_event_sync("dkim_enabled", {
                    "job_id": str(job.id) if job else None,
                    "domain": domain_name, "success": True,
                })

            except Exception as e:
                logger.warning(f"DKIM retry failed for {domain_name}: {e}")
                results.append({"domain": domain_name, "status": "failed", "error": str(e)})
            finally:
                if pfx_path and os.path.exists(pfx_path):
                    os.unlink(pfx_path)

        return {"status": "done", "results": results}


@celery_app.task(name="app.tasks.mailbox_pipeline.run_mailbox_health_check", bind=True, queue="tenant_setup",
                 acks_late=True, reject_on_worker_lost=True)
def run_mailbox_health_check(self, job_id: str):
    """Verify mailboxes from a completed job actually exist in Exchange and can authenticate via SMTP."""
    pfx_path = None
    try:
        with Session(sync_engine) as db:
            job = db.get(MailboxJob, job_id)
            if not job:
                publish_event_sync("mailbox_health_check", {"job_id": job_id, "status": "error", "error": "Job not found"})
                return {"status": "error", "reason": "job_not_found"}

            tenant_id = str(job.tenant_id)
            domain = job.domain

            # Get all DB mailboxes for this tenant + domain
            db_mailboxes = db.execute(
                select(Mailbox).where(
                    Mailbox.tenant_id == tenant_id,
                    Mailbox.email.like(f"%@{domain}"),
                )
            ).scalars().all()

            db_emails = {mb.email.lower() for mb in db_mailboxes}
            db_passwords = {}
            for mb in db_mailboxes:
                if mb.password:
                    try:
                        db_passwords[mb.email.lower()] = decrypt(mb.password)
                    except Exception:
                        pass

        if not db_emails:
            result = {
                "job_id": job_id, "status": "complete",
                "total_in_db": 0, "found_in_exchange": 0,
                "missing": [], "extra_in_exchange": [],
                "smtp_tested": 0, "smtp_ok": 0, "smtp_failed": [],
            }
            publish_event_sync("mailbox_health_check", result)
            return result

        # Publish a "running" event so the frontend shows a spinner
        publish_event_sync("mailbox_health_check", {"job_id": job_id, "status": "running"})

        tenant_data = _load_tenant_data(tenant_id)
        pfx_path = tenant_data.get("cert_pfx_path")

        from app.services.powershell import PowerShellRunner, check_pwsh_available
        if not check_pwsh_available():
            raise RuntimeError("PowerShell (pwsh) not available")

        ps = PowerShellRunner(tenant_data)

        # Get all mailboxes for this domain from Exchange in one call
        from app.services.powershell import escape_ps_string
        safe_domain = escape_ps_string(domain)
        cmd = (
            f"Get-Mailbox -ResultSize Unlimited -RecipientTypeDetails RoomMailbox "
            f"| Where-Object {{ $_.PrimarySmtpAddress -like '*@{safe_domain}' }} "
            f"| ForEach-Object {{ Write-Host \"FOUND: $($_.PrimarySmtpAddress.ToString().ToLower())\" }}"
        )
        stdout, _ = ps.run([cmd], timeout=180)

        exchange_emails = set()
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("FOUND:"):
                exchange_emails.add(line[len("FOUND:"):].strip().lower())

        missing = sorted(db_emails - exchange_emails)
        extra_in_exchange = sorted(exchange_emails - db_emails)
        found = db_emails & exchange_emails

        # SMTP auth test on a sample (up to 5)
        smtp_ok = 0
        smtp_failed = []
        sample = sorted(found)[:5]
        for email in sample:
            pwd = db_passwords.get(email)
            if not pwd:
                continue
            try:
                with smtplib.SMTP("smtp.office365.com", 587, timeout=15) as server:
                    server.starttls()
                    server.login(email, pwd)
                smtp_ok += 1
            except Exception as e:
                err_str = str(e)[:200]
                smtp_failed.append({"email": email, "error": err_str})

        result = {
            "job_id": job_id,
            "status": "complete",
            "total_in_db": len(db_emails),
            "found_in_exchange": len(found),
            "missing": missing,
            "extra_in_exchange": extra_in_exchange,
            "smtp_tested": len(sample),
            "smtp_ok": smtp_ok,
            "smtp_failed": smtp_failed,
        }
        publish_event_sync("mailbox_health_check", result)
        return result

    except Exception as e:
        logger.error(f"Mailbox health check failed for job {job_id}: {e}")
        publish_event_sync("mailbox_health_check", {
            "job_id": job_id, "status": "error", "error": str(e)[:500],
        })
        return {"status": "error", "error": str(e)}
    finally:
        if pfx_path and os.path.exists(pfx_path):
            os.unlink(pfx_path)


@celery_app.task(name="app.tasks.mailbox_pipeline.retry_missing_mailboxes", bind=True, queue="tenant_setup",
                 acks_late=True, reject_on_worker_lost=True)
def retry_missing_mailboxes(self, job_id: str):
    """Re-create mailboxes that exist in DB but are missing from Exchange, then enable SMTP + disable calendar."""
    pfx_path = None
    try:
        with Session(sync_engine) as db:
            job = db.get(MailboxJob, job_id)
            if not job:
                publish_event_sync("retry_missing_result", {"job_id": job_id, "status": "error", "error": "Job not found"})
                return {"status": "error"}

            tenant_id = str(job.tenant_id)
            domain = job.domain
            is_custom_names = job.custom_names is not None

            db_mailboxes = db.execute(
                select(Mailbox).where(Mailbox.tenant_id == tenant_id, Mailbox.email.like(f"%@{domain}"))
            ).scalars().all()

            if not db_mailboxes:
                publish_event_sync("retry_missing_result", {
                    "job_id": job_id, "status": "complete", "missing_count": 0,
                    "created": 0, "failed": 0, "detail": "No mailboxes in DB for this domain",
                })
                return {"status": "complete", "created": 0}

            db_map = {}
            for mb in db_mailboxes:
                pwd = None
                if mb.password:
                    try:
                        pwd = decrypt(mb.password)
                    except Exception:
                        pass
                db_map[mb.email.lower()] = {
                    "email": mb.email,
                    "display_name": mb.display_name or mb.email.split("@")[0],
                    "alias": mb.email.split("@")[0],
                    "password": pwd or "P@ssw0rd!2024#Rand",
                }

            # For custom names, regenerate the full expected identity list to catch
            # mailboxes that failed in the original run and were never saved to DB
            if job.custom_names:
                from app.services.name_generator import generate_custom_identities
                tenant_name = db.get(Tenant, job.tenant_id).name if db.get(Tenant, job.tenant_id) else "Tenant"
                expected = generate_custom_identities(
                    job.custom_names, job.mailbox_count, domain, tenant_name
                )
                for mb in expected:
                    email_key = mb["email"].lower()
                    if email_key not in db_map:
                        db_map[email_key] = {
                            "email": mb["email"],
                            "display_name": mb["display_name"],
                            "alias": mb["alias"],
                            "password": mb["password"],
                        }

        publish_event_sync("retry_missing_result", {"job_id": job_id, "status": "running"})

        tenant_data = _load_tenant_data(tenant_id)
        pfx_path = tenant_data.get("cert_pfx_path")

        from app.services.powershell import PowerShellRunner, check_pwsh_available, escape_ps_string
        if not check_pwsh_available():
            raise RuntimeError("PowerShell (pwsh) not available")

        ps = PowerShellRunner(tenant_data)

        # Step 1: Find which mailboxes actually exist in Exchange
        safe_domain = escape_ps_string(domain)
        cmd = (
            f"Get-Mailbox -ResultSize Unlimited -RecipientTypeDetails RoomMailbox "
            f"| Where-Object {{ $_.PrimarySmtpAddress -like '*@{safe_domain}' }} "
            f"| ForEach-Object {{ Write-Host \"FOUND: $($_.PrimarySmtpAddress.ToString().ToLower())\" }}"
        )
        stdout, _ = ps.run([cmd], timeout=180)

        exchange_emails = set()
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("FOUND:"):
                exchange_emails.add(line[len("FOUND:"):].strip().lower())

        missing_emails = set(db_map.keys()) - exchange_emails
        if not missing_emails:
            publish_event_sync("retry_missing_result", {
                "job_id": job_id, "status": "complete", "missing_count": 0,
                "created": 0, "failed": 0, "detail": "All mailboxes already exist in Exchange",
            })
            return {"status": "complete", "created": 0}

        logger.info(f"Retry job {job_id}: {len(missing_emails)} missing mailboxes to recreate")

        # Step 2: Create missing mailboxes
        # Use email-based Name to avoid "name already in use" conflicts across domains
        domain_tag = domain.split(".")[0]
        create_cmds = []
        missing_list = [db_map[e] for e in sorted(missing_emails)]
        for mb in missing_list:
            safe_pwd = escape_ps_string(mb["password"])
            name_label = mb['alias'] if is_custom_names else mb['display_name']
            unique_name = escape_ps_string(f"{name_label} ({domain_tag})")
            safe_display = escape_ps_string(mb['display_name'])
            safe_alias = escape_ps_string(mb["alias"] + "-" + domain_tag)
            create_cmds.append(
                f"$pwd = ConvertTo-SecureString '{safe_pwd}' -AsPlainText -Force; "
                f"try {{ "
                f"New-Mailbox -Room -Name '{unique_name}' "
                f"-DisplayName '{safe_display}' "
                f"-Alias '{safe_alias}' "
                f"-PrimarySmtpAddress '{mb['email']}' "
                f"-EnableRoomMailboxAccount $true "
                f"-MicrosoftOnlineServicesID '{mb['email']}' "
                f"-RoomMailboxPassword $pwd; "
                f"Write-Host 'CREATED: {mb['email']}' "
                f"}} catch {{ "
                f"if ($_.Exception.Message -like '*already exists*' -or "
                f"$_.Exception.Message -like '*proxy address*already being used*' -or "
                f"$_.Exception.Message -like '*name*already being used*') {{ "
                f"Write-Host 'EXISTS: {mb['email']}' "
                f"}} else {{ "
                f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
                f"}} }}"
            )

        create_stdout, _ = ps.run_batched(create_cmds, batch_size=10, timeout=600)
        succeeded, failed_list = _parse_ps_markers(create_stdout, ["CREATED:", "EXISTS:"])
        created_emails = succeeded["CREATED:"]
        exists_emails = succeeded["EXISTS:"]
        ok_emails = created_emails | exists_emails

        # Save newly created mailboxes to DB (ones that were missing from DB, e.g. original step 7 failures)
        if created_emails:
            with Session(sync_engine) as db:
                dom = db.execute(
                    select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
                ).scalar_one_or_none()
                domain_id = dom.id if dom else None
                for email in created_emails:
                    existing = db.execute(
                        select(Mailbox).where(Mailbox.email == email)
                    ).scalar_one_or_none()
                    if not existing and email in db_map:
                        mb = db_map[email]
                        db.add(Mailbox(
                            tenant_id=tenant_id,
                            domain_id=domain_id,
                            display_name=mb["display_name"],
                            email=mb["email"],
                            password=encrypt(mb["password"]),
                        ))
                db.commit()

        # Step 3: Enable SMTP for successfully created mailboxes
        if ok_emails:
            smtp_cmds = []
            for email in sorted(ok_emails):
                smtp_cmds.append(
                    f"try {{ "
                    f"Set-CASMailbox -Identity '{email}' -SmtpClientAuthenticationDisabled $false; "
                    f"Write-Host 'ENABLED: {email}' "
                    f"}} catch {{ "
                    f"Write-Host 'FAILED: {email} - ' $_.Exception.Message "
                    f"}}"
                )
            smtp_stdout, _ = ps.run_batched(smtp_cmds, batch_size=10, timeout=600)

            # Update smtp_enabled in DB for successfully enabled mailboxes
            smtp_succeeded, _ = _parse_ps_markers(smtp_stdout, ["ENABLED:"])
            enabled_emails = smtp_succeeded["ENABLED:"]
            if enabled_emails:
                with Session(sync_engine) as db:
                    for email in enabled_emails:
                        mb = db.execute(
                            select(Mailbox).where(Mailbox.email == email)
                        ).scalar_one_or_none()
                        if mb:
                            mb.smtp_enabled = True
                    db.commit()

        # Step 4: Disable calendar processing for successfully created mailboxes
        if ok_emails:
            cal_cmds = []
            for email in sorted(ok_emails):
                cal_cmds.append(
                    f"try {{ "
                    f"Set-CalendarProcessing -Identity '{email}' "
                    f"-AutomateProcessing None -DeleteComments $false -DeleteSubject $false; "
                    f"Write-Host 'CONFIGURED: {email}' "
                    f"}} catch {{ "
                    f"Write-Host 'FAILED: {email} - ' $_.Exception.Message "
                    f"}}"
                )
            ps.run_batched(cal_cmds, batch_size=10, timeout=600)

        # Build result
        detail = f"Retried {len(missing_emails)} missing mailboxes: Created {len(created_emails)}, Already existed {len(exists_emails)}, Failed {len(failed_list)}"
        if failed_list:
            detail += "\n" + "\n".join(f"  {email} - {reason}" for email, reason in failed_list[:20])

        # Update job step_results to reflect actual mailbox count after retry
        with Session(sync_engine) as db:
            job = db.get(MailboxJob, job_id)
            if job:
                actual_count = db.execute(
                    select(Mailbox).where(Mailbox.tenant_id == tenant_id, Mailbox.email.like(f"%@{domain}"))
                ).scalars().all()
                total_ok = len(actual_count)
                total_failed = job.mailbox_count - total_ok
                step7_detail = f"Created: {total_ok}, Existed: 0, Failed: {total_failed}"
                if not job.step_results:
                    job.step_results = {}
                job.step_results["7"] = {
                    "status": "success" if total_failed == 0 else "warning",
                    "message": "",
                    "detail": step7_detail,
                }
                flag_modified(job, "step_results")
                db.commit()

        result = {
            "job_id": job_id,
            "status": "complete",
            "missing_count": len(missing_emails),
            "created": len(created_emails),
            "existed": len(exists_emails),
            "failed": len(failed_list),
            "failed_list": [{"email": e, "error": r} for e, r in failed_list[:20]],
            "detail": detail,
        }
        publish_event_sync("retry_missing_result", result)
        logger.info(f"Retry job {job_id}: {detail}")
        return result

    except Exception as e:
        logger.error(f"Retry missing mailboxes failed for job {job_id}: {e}")
        publish_event_sync("retry_missing_result", {
            "job_id": job_id, "status": "error", "error": str(e)[:500],
        })
        return {"status": "error", "error": str(e)}
    finally:
        if pfx_path and os.path.exists(pfx_path):
            os.unlink(pfx_path)


# ── Fix Security Defaults ───────────────────────────────────────────────

@celery_app.task(name="app.tasks.mailbox_pipeline.fix_security_defaults", queue="tenant_setup")
def fix_security_defaults(tenant_id: str):
    """Disable security defaults and re-enable SMTP auth on a tenant."""
    import requests
    from app.selenium_worker.security_settings import (
        disable_security_defaults as _disable_sd,
        disable_mfa_registration_campaign,
        enable_smtp_auth_org,
    )

    try:
        with Session(sync_engine) as db:
            tenant = db.get(Tenant, tenant_id)
            if not tenant:
                raise ValueError(f"Tenant {tenant_id} not found")

            ms_tenant_id = decrypt_bytes(tenant.tenant_id_ms).decode() if tenant.tenant_id_ms else None
            client_id = decrypt_bytes(tenant.client_id).decode() if tenant.client_id else None
            client_secret = decrypt_bytes(tenant.client_secret).decode() if tenant.client_secret else None

            if not all([ms_tenant_id, client_id, client_secret]):
                raise ValueError("Tenant missing app credentials (tenant_id_ms, client_id, or client_secret)")

        # Get app token
        r = requests.post(
            f"https://login.microsoftonline.com/{ms_tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        token = r.json().get("access_token")
        if not token:
            raise ValueError(f"Failed to get app token: {r.json().get('error_description', 'Unknown error')}")

        detail_parts = []

        # 1. Disable security defaults
        if _disable_sd(token):
            detail_parts.append("Security Defaults disabled")
        else:
            detail_parts.append("Security Defaults: already disabled or failed")

        # 2. Disable MFA registration campaign
        if disable_mfa_registration_campaign(token):
            detail_parts.append("MFA campaign disabled")

        # 3. Enable org-wide SMTP auth
        if enable_smtp_auth_org(token, tenant_id=ms_tenant_id):
            detail_parts.append("Org SMTP auth enabled")
        else:
            detail_parts.append("Org SMTP auth: failed (may need PowerShell)")

        detail = "; ".join(detail_parts)
        result = {"tenant_id": tenant_id, "status": "complete", "detail": detail}
        publish_event_sync("fix_security_defaults", result)
        logger.info(f"Fix security defaults for tenant {tenant_id}: {detail}")
        return result

    except Exception as e:
        logger.error(f"Fix security defaults failed for tenant {tenant_id}: {e}")
        result = {"tenant_id": tenant_id, "status": "error", "error": str(e)[:500]}
        publish_event_sync("fix_security_defaults", result)
        return result
