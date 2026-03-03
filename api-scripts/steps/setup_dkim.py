"""Step 5: Setup DKIM — create CNAME records in Cloudflare, then enable DKIM signing."""

import time
from log import info, ok, warn, err
from services.graph_api import GraphClient
from services.cloudflare import CloudflareClient
from services.powershell import PowerShellRunner, check_pwsh_available

DKIM_SELECTORS = ["selector1", "selector2"]
BACKOFF_SCHEDULE = [30, 60, 120]


def run(tenant: dict, domain: str = None, **kwargs) -> dict:
    if not domain:
        err("--domain is required for setup-dkim step")
        return {"status": "error", "reason": "missing_domain"}

    info(f"Step 5: Setup DKIM for '{domain}'")

    graph = GraphClient(tenant["tenant_id"], tenant["client_id"], tenant["client_secret"])
    cf = CloudflareClient()
    org_domain = tenant["org_domain"]
    domain_dashed = domain.replace(".", "-")

    # Create DKIM CNAME records in Cloudflare
    for selector in DKIM_SELECTORS:
        cname_name = f"{selector}._domainkey.{domain}"
        cname_target = f"{selector}-{domain_dashed}._domainkey.{org_domain}"
        info(f"Creating CNAME: {cname_name} → {cname_target}")
        cf.upsert_dns_record(domain, "CNAME", cname_name, cname_target, proxied=False)
        ok(f"DKIM CNAME for {selector} created")

    # Enable DKIM — PowerShell first (Graph beta dkimSigningConfigs is unreliable)
    info("Enabling DKIM signing")

    if check_pwsh_available():
        ps = PowerShellRunner(tenant)
        try:
            ps.run([
                f"New-DkimSigningConfig -DomainName '{domain}' -Enabled $true",
            ])
            ok("DKIM signing enabled via PowerShell (New-DkimSigningConfig)")
            return {"status": "enabled", "domain": domain, "method": "powershell_new"}
        except RuntimeError as e:
            if "already exists" in str(e).lower():
                info("DKIM config already exists, trying to enable it")
                try:
                    ps.run([
                        f"Set-DkimSigningConfig -Identity '{domain}' -Enabled $true",
                    ])
                    ok("DKIM signing enabled via PowerShell (Set-DkimSigningConfig)")
                    return {"status": "enabled", "domain": domain, "method": "powershell_set"}
                except RuntimeError as e2:
                    warn(f"PowerShell Set-DkimSigningConfig failed: {e2}")
            else:
                warn(f"PowerShell New-DkimSigningConfig failed: {e}")

    # Graph beta fallback with retry
    info("Trying Graph beta API to enable DKIM")
    dkim_path = f"/admin/exchange/dkimSigningConfigs/{domain}"

    for attempt, wait in enumerate([0] + BACKOFF_SCHEDULE, start=1):
        if wait > 0:
            info(f"Waiting {wait}s for DNS propagation...")
            time.sleep(wait)

        try:
            graph.patch(dkim_path, beta=True, json_data={"isEnabled": True})
            ok("DKIM signing enabled via Graph beta")
            return {"status": "enabled", "domain": domain, "method": "graph_beta", "attempts": attempt}
        except RuntimeError as e:
            if attempt <= len(BACKOFF_SCHEDULE):
                warn(f"Graph beta attempt {attempt} failed: {e}")
            else:
                err(f"Graph beta failed after all retries: {e}")

    warn("DKIM CNAME records created but enabling failed — may need manual enable or DNS propagation")
    return {"status": "cnames_created", "domain": domain,
            "note": "DKIM CNAMEs created, enabling may require more time for DNS propagation"}
