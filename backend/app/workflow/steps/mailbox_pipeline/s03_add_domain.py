"""Step 3: Add domain to tenant and create DNS records."""

import logging
import time

from sqlalchemy import select

from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


class AddDomainStep(BaseStep):
    name = "Add Domain"
    max_attempts = 3
    is_blocking = True

    def execute(self, ctx) -> StepResult:
        graph = ctx.shared.get("graph")
        if not graph:
            from app.services.graph_client import MicrosoftGraphClient
            td = ctx.tenant_data
            graph = MicrosoftGraphClient(td["tenant_id"], td["client_id"], td["client_secret"])
            ctx.shared["graph"] = graph

        domain = ctx.shared.get("domain") or ctx.job.config.get("domain")
        cf = ctx.shared.get("cf")
        if not cf:
            from app.services.cloudflare_client import CloudflareClient
            cf_email = ctx.shared.get("cf_email") or ctx.job.config.get("cf_email")
            cf_api_key = ctx.shared.get("cf_api_key") or ctx.job.config.get("cf_api_key")

            if not cf_email or not cf_api_key:
                from app.models import CloudflareConfig
                from app.services.encryption import decrypt
                result = ctx.db.execute(
                    select(CloudflareConfig).where(CloudflareConfig.is_default == True)  # noqa: E712
                )
                cf_config = result.scalar_one_or_none()
                if cf_config:
                    cf_email = cf_config.cf_email
                    cf_api_key = decrypt(cf_config.cf_api_key)

            if not cf_email or not cf_api_key:
                raise RuntimeError("No Cloudflare credentials available")

            cf = CloudflareClient(api_key=cf_api_key, email=cf_email)
            ctx.shared["cf"] = cf

        # Add domain to Microsoft tenant
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

        # Create DNS records
        for rec in verification_records:
            if rec.get("recordType") == "Txt":
                try:
                    cf.upsert_dns_record(domain, "TXT", domain, rec.get("text", ""), proxied=False)
                except RuntimeError as e:
                    if "already exists" not in str(e).lower():
                        raise

        mx_host = domain.replace(".", "-") + ".mail.protection.outlook.com"
        try:
            cf.upsert_dns_record(domain, "MX", domain, mx_host, priority=0, proxied=False)
        except RuntimeError as e:
            if "already exists" not in str(e).lower():
                raise

        spf_value = "v=spf1 include:spf.protection.outlook.com -all"
        try:
            cf.create_dns_record(domain, "TXT", domain, spf_value, proxied=False)
        except RuntimeError:
            pass  # May already exist

        try:
            cf.upsert_dns_record(domain, "CNAME", f"autodiscover.{domain}",
                                 "autodiscover.outlook.com", proxied=False)
        except RuntimeError as e:
            if "already exists" not in str(e).lower():
                raise

        return StepResult(status="success")
