"""Step 4: Verify domain with Microsoft."""

import logging
import time

from sqlalchemy import select

from app.models import Domain
from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


class VerifyDomainStep(BaseStep):
    name = "Verify Domain"
    max_attempts = 2
    is_blocking = True

    def execute(self, ctx) -> StepResult:
        graph = ctx.shared["graph"]
        domain = ctx.shared.get("domain") or ctx.job.config.get("domain")
        tenant_id = str(ctx.job.tenant_id)

        # Check if already verified
        verified = False
        try:
            resp = graph.get(f"/domains/{domain}")
            if resp.json().get("isVerified"):
                verified = True
                logger.info(f"Domain {domain} already verified")
        except RuntimeError:
            pass

        if not verified:
            backoffs = [5, 15, 30, 60]
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
                try:
                    resp = graph.post(f"/domains/{domain}/verify")
                    verified = resp.json().get("isVerified", False)
                except RuntimeError:
                    pass
                if not verified:
                    raise RuntimeError(f"Domain '{domain}' could not be verified")

        # Save to DB
        existing = ctx.db.execute(
            select(Domain).where(Domain.tenant_id == tenant_id, Domain.domain == domain)
        ).scalar_one_or_none()
        if not existing:
            ctx.db.add(Domain(tenant_id=tenant_id, domain=domain, is_verified=True))
        else:
            existing.is_verified = True
        ctx.db.commit()

        return StepResult(status="success")
