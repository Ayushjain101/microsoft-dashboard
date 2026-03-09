"""Step 7: Create mailboxes via PowerShell."""

import logging
import time

from sqlalchemy import select

from app.models import Domain, Mailbox
from app.services.encryption import encrypt
from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


def _parse_ps_markers(stdout: str, success_markers: list[str], fail_marker: str = "FAILED:"):
    """Parse PowerShell stdout for success/failure markers."""
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


class CreateMailboxesStep(BaseStep):
    name = "Create Mailboxes"
    max_attempts = 2
    backoff_base = 15.0
    is_blocking = True

    def execute(self, ctx) -> StepResult:
        from app.services.powershell import PowerShellRunner, check_pwsh_available, ensure_exchange_module, escape_ps_string
        from app.services.name_generator import generate_mailbox_identities, generate_custom_identities

        domain = ctx.shared.get("domain") or ctx.job.config.get("domain")
        tenant_id = str(ctx.job.tenant_id)
        mailbox_count = ctx.shared.get("mailbox_count") or ctx.job.config.get("mailbox_count", 50)
        custom_names = ctx.shared.get("custom_names") or ctx.job.config.get("custom_names")

        if not check_pwsh_available():
            raise RuntimeError("PowerShell (pwsh) not available")
        ensure_exchange_module()

        if custom_names:
            identities = generate_custom_identities(custom_names, mailbox_count, domain, ctx.tenant_data["tenant_name"])
        else:
            identities = generate_mailbox_identities(mailbox_count, domain, ctx.tenant_data["tenant_name"])

        ps = PowerShellRunner(ctx.tenant_data)

        # Domain readiness probe
        domain_ready = False
        probe_alias = f"_probe-{domain.split('.')[0]}"
        probe_email = f"{probe_alias}@{domain}"
        backoff_waits = [0, 15, 30, 60, 120, 120, 120, 120, 120, 120, 120, 120]
        for wait_secs in backoff_waits:
            if wait_secs:
                logger.info(f"Domain {domain} not ready, waiting {wait_secs}s...")
                ctx.publish_progress(f"Waiting for Exchange to provision domain ({wait_secs}s)")
                time.sleep(wait_secs)
            try:
                safe_probe_alias = escape_ps_string(probe_alias)
                ps.run([
                    f"$pwd = ConvertTo-SecureString 'ProbeP@ss1!' -AsPlainText -Force; "
                    f"New-Mailbox -Room -Name '{safe_probe_alias}' "
                    f"-Alias '{safe_probe_alias}' "
                    f"-PrimarySmtpAddress '{probe_email}' "
                    f"-EnableRoomMailboxAccount $true "
                    f"-MicrosoftOnlineServicesID '{probe_email}' "
                    f"-RoomMailboxPassword $pwd"
                ])
                try:
                    ps.run([f"Remove-Mailbox -Identity '{probe_email}' -Confirm:$false"])
                except RuntimeError:
                    pass
                domain_ready = True
                break
            except RuntimeError as e:
                if "not an accepted domain" in str(e).lower():
                    continue
                elif "already exists" in str(e).lower() or "already being used" in str(e).lower():
                    try:
                        ps.run([f"Remove-Mailbox -Identity '{probe_email}' -Confirm:$false"])
                    except RuntimeError:
                        pass
                    domain_ready = True
                    break
                else:
                    raise

        if not domain_ready:
            raise RuntimeError(
                f"Domain '{domain}' is not usable for mailbox creation after {sum(backoff_waits)}s. "
                f"Exchange Online may need more time. Please retry later."
            )

        # Build commands
        domain_tag = domain.split(".")[0]
        commands = []
        for mb in identities:
            safe_pwd = escape_ps_string(mb["password"])
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
                f"if ($_.Exception.Message -like '*proxy address*already being used*' -or "
                f"$_.Exception.Message -like '*name*already being used*') {{ "
                f"Write-Host 'PROXY: {mb['email']}' "
                f"}} elseif ($_.Exception.Message -like '*already exists*') {{ "
                f"Write-Host 'EXISTS: {mb['email']}' "
                f"}} else {{ "
                f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
                f"}} }}"
            )

        stdout, _ = ps.run_batched(commands, batch_size=25, timeout=900)

        # Parse first-pass
        succeeded_first, failed_first = _parse_ps_markers(stdout, ["CREATED:", "EXISTS:"])
        ok_first = succeeded_first["CREATED:"] | succeeded_first["EXISTS:"]
        proxy_conflicts, _ = _parse_ps_markers(stdout, ["PROXY:"])
        proxy_emails = proxy_conflicts["PROXY:"]

        # Handle proxy conflicts
        if proxy_emails and custom_names:
            from app.services.name_generator import _generate_alias_variations
            logger.info(f"Step 7: {len(proxy_emails)} proxy conflicts, generating replacements")
            email_to_idx = {mb["email"].lower(): i for i, mb in enumerate(identities)}
            used_aliases = {mb["alias"] for mb in identities}
            for conflict_email in proxy_emails:
                idx = email_to_idx.get(conflict_email)
                if idx is None:
                    continue
                mb = identities[idx]
                variations = _generate_alias_variations(mb["first_name"], mb["last_name"])
                replacement = None
                for v in variations:
                    if v not in used_aliases:
                        replacement = v
                        break
                if replacement:
                    used_aliases.add(replacement)
                    new_email = f"{replacement}@{domain}"
                    mb["alias"] = replacement
                    mb["email"] = new_email
                    email_to_idx[new_email.lower()] = idx
                    safe_pwd = escape_ps_string(mb["password"])
                    name_label = mb['alias']
                    unique_name = escape_ps_string(f"{name_label} ({domain_tag})")
                    safe_display = escape_ps_string(mb['display_name'])
                    safe_alias = escape_ps_string(f"{mb['alias']}-{domain_tag}")
                    commands[idx] = (
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
                        f"if ($_.Exception.Message -like '*proxy address*already being used*' -or "
                        f"$_.Exception.Message -like '*name*already being used*') {{ "
                        f"Write-Host 'PROXY: {mb['email']}' "
                        f"}} elseif ($_.Exception.Message -like '*already exists*') {{ "
                        f"Write-Host 'EXISTS: {mb['email']}' "
                        f"}} else {{ "
                        f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
                        f"}} }}"
                    )
                else:
                    logger.warning(f"Step 7: no replacement alias for {mb['email']}")
            replacement_cmds = [commands[email_to_idx[e]] for e in proxy_emails
                                if e in email_to_idx and identities[email_to_idx[e]]["email"].lower() != e]
            if replacement_cmds:
                repl_stdout, _ = ps.run_batched(replacement_cmds, batch_size=25, timeout=900)
                stdout = stdout + "\n" + repl_stdout
                repl_ok, _ = _parse_ps_markers(repl_stdout, ["CREATED:", "EXISTS:"])
                ok_first |= repl_ok["CREATED:"] | repl_ok["EXISTS:"]

        # Retry failures
        remaining_failures = failed_first
        for retry_attempt in range(1, 3):
            to_retry = [(e, r) for e, r in remaining_failures if e.lower() not in ok_first]
            if not to_retry:
                break
            has_domain_reject = any("not an accepted domain" in r.lower() for _, r in to_retry)
            wait = 60 if has_domain_reject else 15
            logger.info(f"Step 7 retry {retry_attempt}: {len(to_retry)} failed, waiting {wait}s...")
            time.sleep(wait)
            retry_emails = {e.lower() for e, _ in to_retry}
            retry_commands = [cmd for cmd, mb in zip(commands, identities) if mb["email"].lower() in retry_emails]
            retry_stdout, _ = ps.run_batched(retry_commands, batch_size=25, timeout=900)
            stdout = stdout + "\n" + retry_stdout
            retry_ok, remaining_failures = _parse_ps_markers(retry_stdout, ["CREATED:", "EXISTS:"])
            ok_first |= retry_ok["CREATED:"] | retry_ok["EXISTS:"]

        # Final parse
        succeeded, failed_list = _parse_ps_markers(stdout, ["CREATED:", "EXISTS:"])
        created_emails = succeeded["CREATED:"]
        exists_emails = succeeded["EXISTS:"]
        ok_emails = created_emails | exists_emails
        failed_list = [(e, r) for e, r in failed_list if e.lower() not in ok_emails]
        failed_list = [(e, r) for e, r in failed_list if e.lower() not in proxy_emails or e.lower() in ok_emails]

        # Save to DB
        dom = ctx.db.execute(
            select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
        ).scalar_one_or_none()
        domain_id = dom.id if dom else None

        for mb in identities:
            if mb["email"].lower() not in ok_emails:
                continue
            existing = ctx.db.execute(
                select(Mailbox).where(Mailbox.email == mb["email"])
            ).scalar_one_or_none()
            if not existing:
                ctx.db.add(Mailbox(
                    tenant_id=tenant_id,
                    domain_id=domain_id,
                    display_name=mb["display_name"],
                    email=mb["email"],
                    password=encrypt(mb["password"]),
                ))
        ctx.db.commit()

        detail = f"Created: {len(created_emails)}, Existed: {len(exists_emails)}, Failed: {len(failed_list)}"
        if failed_list:
            detail += "\n" + "\n".join(f"  {email} - {reason}" for email, reason in failed_list[:20])

        # Pass identities forward for steps 8 & 9
        ok_identities = [mb for mb in identities if mb["email"].lower() in ok_emails]

        if len(ok_emails) == 0 and failed_list:
            return StepResult(status="failed", detail=detail)
        elif failed_list:
            return StepResult(status="warning", detail=detail, data={"identities": ok_identities, "ok_emails": ok_emails})
        else:
            return StepResult(status="success", detail=detail, data={"identities": ok_identities, "ok_emails": ok_emails})
