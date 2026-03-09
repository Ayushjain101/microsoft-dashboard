"""Step 6: Setup DMARC DNS record."""

import logging

from sqlalchemy import select

from app.models import Domain
from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


class SetupDmarcStep(BaseStep):
    name = "Setup DMARC"
    max_attempts = 2
    is_blocking = False

    def execute(self, ctx) -> StepResult:
        domain = ctx.shared.get("domain") or ctx.job.config.get("domain")
        tenant_id = str(ctx.job.tenant_id)
        cf = ctx.shared["cf"]

        dmarc_value = f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}"
        cf.upsert_dns_record(domain, "TXT", f"_dmarc.{domain}", dmarc_value, proxied=False)

        dom = ctx.db.execute(
            select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
        ).scalar_one_or_none()
        if dom:
            dom.dmarc_created = True
            ctx.db.commit()

        return StepResult(status="success")
