"""Step 8: Enable per-mailbox SMTP AUTH via PowerShell."""

import json
from pathlib import Path
from config import API_OUTPUT
from log import info, ok, warn, err
from services.powershell import PowerShellRunner, check_pwsh_available


def run(tenant: dict, domain: str = None, **kwargs) -> dict:
    if not domain:
        err("--domain is required for enable-smtp step")
        return {"status": "error", "reason": "missing_domain"}

    info(f"Step 8: Enable per-mailbox SMTP for '{domain}'")

    if not check_pwsh_available():
        err("PowerShell (pwsh) not available")
        return {"status": "error", "reason": "pwsh_not_found"}

    # Load mailbox list from step 7 output
    mailbox_file = API_OUTPUT / f"{tenant['tenant_name']}_mailboxes.json"
    if not mailbox_file.exists():
        err(f"Mailbox file not found: {mailbox_file}")
        err("Run create-mailboxes step first")
        return {"status": "error", "reason": "mailbox_file_missing"}

    with open(mailbox_file) as f:
        mailbox_data = json.load(f)

    identities = mailbox_data.get("identities", [])
    if not identities:
        err("No mailbox identities found in output file")
        return {"status": "error", "reason": "no_identities"}

    info(f"Enabling SMTP for {len(identities)} mailboxes")

    ps = PowerShellRunner(tenant)

    # Build Set-CASMailbox commands
    commands = []
    for mb in identities:
        commands.append(
            f"try {{ "
            f"Set-CASMailbox -Identity '{mb['email']}' -SmtpClientAuthenticationDisabled $false; "
            f"Write-Host 'ENABLED: {mb['email']}' "
            f"}} catch {{ "
            f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
            f"}}"
        )

    info("Running PowerShell to enable SMTP (this may take a while)...")
    try:
        stdout, stderr = ps.run_batched(commands, batch_size=10, timeout=600)
    except RuntimeError as e:
        err(f"PowerShell batch failed: {e}")
        return {"status": "error", "reason": str(e)}

    # Parse results
    enabled, failed = [], []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("ENABLED:"):
            enabled.append(line.split("ENABLED:")[1].strip())
        elif line.startswith("FAILED:"):
            failed.append(line.split("FAILED:")[1].strip())

    info(f"Results: {len(enabled)} enabled, {len(failed)} failed")

    if failed:
        for f_item in failed:
            warn(f"Failed: {f_item}")

    ok(f"Step 8 complete: {len(enabled)} SMTP enabled, {len(failed)} failed")
    return {"status": "ok", "enabled": len(enabled), "failed": len(failed)}
