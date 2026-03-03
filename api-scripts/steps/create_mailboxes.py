"""Step 7: Create room mailboxes via PowerShell."""

import json
from pathlib import Path
from config import API_OUTPUT, MAILBOX_COUNT
from log import info, ok, warn, err
from name_generator import generate_mailbox_identities
from services.powershell import PowerShellRunner, check_pwsh_available, ensure_exchange_module


def run(tenant: dict, domain: str = None, count: int = None, **kwargs) -> dict:
    if not domain:
        err("--domain is required for create-mailboxes step")
        return {"status": "error", "reason": "missing_domain"}

    count = count or MAILBOX_COUNT

    info(f"Step 7: Create {count} room mailboxes on '{domain}'")

    if not check_pwsh_available():
        err("PowerShell (pwsh) not available")
        return {"status": "error", "reason": "pwsh_not_found"}

    info("Ensuring ExchangeOnlineManagement module is installed")
    ensure_exchange_module()

    tenant_short = tenant["tenant_name"]
    identities = generate_mailbox_identities(count, domain, tenant_short)

    info(f"Generated {len(identities)} mailbox identities")

    ps = PowerShellRunner(tenant)

    # Build PowerShell commands for each mailbox
    commands = []
    for mb in identities:
        safe_pwd = mb["password"].replace("'", "''")
        commands.append(
            f"$pwd = ConvertTo-SecureString '{safe_pwd}' -AsPlainText -Force; "
            f"try {{ "
            f"New-Mailbox -Room -Name '{mb['display_name']}' "
            f"-Alias '{mb['alias']}' "
            f"-PrimarySmtpAddress '{mb['email']}' "
            f"-EnableRoomMailboxAccount $true "
            f"-MicrosoftOnlineServicesID '{mb['email']}' "
            f"-RoomMailboxPassword $pwd; "
            f"Write-Host 'CREATED: {mb['email']}' "
            f"}} catch {{ "
            f"if ($_.Exception.Message -like '*already exists*' -or $_.Exception.Message -like '*proxy address*already being used*') {{ "
            f"Write-Host 'EXISTS: {mb['email']}' "
            f"}} else {{ "
            f"Write-Host 'FAILED: {mb['email']} - ' $_.Exception.Message "
            f"}} }}"
        )

    info("Running PowerShell to create mailboxes (this may take a while)...")
    try:
        stdout, stderr = ps.run_batched(commands, batch_size=10, timeout=600)
    except RuntimeError as e:
        err(f"PowerShell batch failed: {e}")
        return {"status": "error", "reason": str(e)}

    # Parse results
    created, existed, failed = [], [], []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("CREATED:"):
            created.append(line.split("CREATED:")[1].strip())
        elif line.startswith("EXISTS:"):
            existed.append(line.split("EXISTS:")[1].strip())
        elif line.startswith("FAILED:"):
            failed.append(line.split("FAILED:")[1].strip())

    info(f"Results: {len(created)} created, {len(existed)} existed, {len(failed)} failed")

    # Save results to output file
    API_OUTPUT.mkdir(parents=True, exist_ok=True)
    output_path = API_OUTPUT / f"{tenant['tenant_name']}_mailboxes.json"
    output_data = {
        "tenant": tenant["tenant_name"],
        "domain": domain,
        "identities": identities,
        "results": {
            "created": created,
            "existed": existed,
            "failed": failed,
        },
    }
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    ok(f"Mailbox results saved to {output_path}")

    # Save CSV alongside JSON
    csv_path = API_OUTPUT / f"{tenant['tenant_name']}_mailboxes.csv"
    with open(csv_path, "w") as f:
        f.write("first_name,last_name,display_name,email,password\n")
        for mb in identities:
            f.write(f"{mb['first_name']},{mb['last_name']},{mb['display_name']},{mb['email']},{mb['password']}\n")
    ok(f"Mailbox CSV saved to {csv_path}")

    if failed:
        for f_item in failed:
            warn(f"Failed: {f_item}")

    ok(f"Step 7 complete: {len(created)} created, {len(existed)} existed, {len(failed)} failed")
    return {"status": "ok", "created": len(created), "existed": len(existed),
            "failed": len(failed), "output_file": str(output_path)}
