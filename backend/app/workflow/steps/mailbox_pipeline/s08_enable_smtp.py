"""Step 8: Enable SMTP authentication for created mailboxes."""

import logging
import time

from sqlalchemy import select

from app.models import Mailbox
from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


def _parse_ps_markers(stdout: str, success_markers: list[str], fail_marker: str = "FAILED:"):
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


class EnableSmtpStep(BaseStep):
    name = "Enable SMTP"
    max_attempts = 2
    is_blocking = False

    def preconditions(self, ctx) -> bool:
        return bool(ctx.shared.get("identities"))

    def execute(self, ctx) -> StepResult:
        from app.services.powershell import PowerShellRunner
        identities = ctx.shared["identities"]

        ps = PowerShellRunner(ctx.tenant_data)
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

        smtp_stdout, _ = ps.run_batched(smtp_commands, batch_size=25, timeout=900)
        smtp_succeeded, smtp_failed = _parse_ps_markers(smtp_stdout, ["ENABLED:"])
        enabled_emails = smtp_succeeded["ENABLED:"]

        # Retry once after 5s
        if smtp_failed:
            failed_smtp_emails = {email.lower() for email, _ in smtp_failed}
            retry_cmds = [cmd for cmd, mb in zip(smtp_commands, identities)
                          if mb["email"].lower() in failed_smtp_emails]
            if retry_cmds:
                logger.info(f"Step 8: retrying {len(retry_cmds)} failed SMTP enables after 5s")
                time.sleep(5)
                retry_stdout, _ = ps.run_batched(retry_cmds, batch_size=25, timeout=900)
                retry_succ, retry_fail = _parse_ps_markers(retry_stdout, ["ENABLED:"])
                enabled_emails = enabled_emails | retry_succ["ENABLED:"]
                smtp_failed = [(e, r) for e, r in retry_fail if e.lower() not in enabled_emails]

        # Update DB
        for mb in identities:
            if mb["email"].lower() not in enabled_emails:
                continue
            existing = ctx.db.execute(
                select(Mailbox).where(Mailbox.email == mb["email"])
            ).scalar_one_or_none()
            if existing:
                existing.smtp_enabled = True
        ctx.db.commit()

        detail = f"Enabled: {len(enabled_emails)}, Failed: {len(smtp_failed)}"
        if smtp_failed:
            detail += "\n" + "\n".join(f"  {email} - {reason}" for email, reason in smtp_failed[:20])

        if smtp_failed and not enabled_emails:
            return StepResult(status="failed", detail=detail)
        elif smtp_failed:
            return StepResult(status="warning", detail=detail)
        else:
            return StepResult(status="success", detail=detail)
