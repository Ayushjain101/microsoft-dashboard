"""Step 9: Disable calendar processing for created mailboxes."""

import logging
import time

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


class DisableCalendarStep(BaseStep):
    name = "Disable Calendar Processing"
    max_attempts = 2
    is_blocking = False

    def preconditions(self, ctx) -> bool:
        return bool(ctx.shared.get("identities"))

    def execute(self, ctx) -> StepResult:
        from app.services.powershell import PowerShellRunner
        identities = ctx.shared["identities"]

        ps = PowerShellRunner(ctx.tenant_data)
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

        cal_stdout, _ = ps.run_batched(cal_commands, batch_size=25, timeout=900)
        cal_succeeded, cal_failed = _parse_ps_markers(cal_stdout, ["CONFIGURED:"])
        configured_emails = cal_succeeded["CONFIGURED:"]

        # Retry once after 5s
        if cal_failed:
            failed_cal_emails = {email.lower() for email, _ in cal_failed}
            retry_cmds = [cmd for cmd, mb in zip(cal_commands, identities)
                          if mb["email"].lower() in failed_cal_emails]
            if retry_cmds:
                logger.info(f"Step 9: retrying {len(retry_cmds)} failed calendar configs after 5s")
                time.sleep(5)
                retry_stdout, _ = ps.run_batched(retry_cmds, batch_size=25, timeout=900)
                retry_succ, retry_fail = _parse_ps_markers(retry_stdout, ["CONFIGURED:"])
                configured_emails = configured_emails | retry_succ["CONFIGURED:"]
                cal_failed = [(e, r) for e, r in retry_fail if e.lower() not in configured_emails]

        detail = f"Configured: {len(configured_emails)}, Failed: {len(cal_failed)}"
        if cal_failed:
            detail += "\n" + "\n".join(f"  {email} - {reason}" for email, reason in cal_failed[:20])

        if cal_failed and not configured_emails:
            return StepResult(status="failed", detail=detail)
        elif cal_failed:
            return StepResult(status="warning", detail=detail)
        else:
            return StepResult(status="success", detail=detail)
