"""Step 5: Setup DKIM signing configuration."""

import logging

from sqlalchemy import select

from app.models import Domain
from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


class SetupDkimStep(BaseStep):
    name = "Setup DKIM"
    max_attempts = 2
    is_blocking = False  # Warning on failure

    def execute(self, ctx) -> StepResult:
        domain = ctx.shared.get("domain") or ctx.job.config.get("domain")
        tenant_id = str(ctx.job.tenant_id)
        org_domain = ctx.tenant_data["org_domain"]
        cf = ctx.shared.get("cf")

        domain_dashed = domain.replace(".", "-")
        for selector in ["selector1", "selector2"]:
            cname_name = f"{selector}._domainkey.{domain}"
            cname_target = f"{selector}-{domain_dashed}._domainkey.{org_domain}"
            cf.upsert_dns_record(domain, "CNAME", cname_name, cname_target, proxied=False)

        dkim_ok = False
        from app.services.powershell import PowerShellRunner, check_pwsh_available
        if check_pwsh_available():
            ps = PowerShellRunner(ctx.tenant_data)
            try:
                ps.run([f"New-DkimSigningConfig -DomainName '{domain}' -Enabled $true"])
                dkim_ok = True
            except RuntimeError as e:
                if "already exists" in str(e).lower():
                    try:
                        ps.run([f"Set-DkimSigningConfig -Identity '{domain}' -Enabled $true"])
                        dkim_ok = True
                    except RuntimeError:
                        logger.warning(f"DKIM fallback failed for {domain}", exc_info=True)

        dom = ctx.db.execute(
            select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
        ).scalar_one_or_none()
        if dom and dkim_ok:
            dom.dkim_enabled = True
            ctx.db.commit()

        if dkim_ok:
            return StepResult(status="success")
        else:
            return StepResult(
                status="warning",
                detail="DKIM signing config not enabled — Microsoft may need more time. Use DKIM button to retry later."
            )
