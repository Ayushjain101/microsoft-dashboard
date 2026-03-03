"""Step 6: Setup DMARC TXT record in Cloudflare."""

from log import info, ok, warn, err
from services.cloudflare import CloudflareClient


def run(tenant: dict, domain: str = None, **kwargs) -> dict:
    if not domain:
        err("--domain is required for setup-dmarc step")
        return {"status": "error", "reason": "missing_domain"}

    info(f"Step 6: Setup DMARC for '{domain}'")

    cf = CloudflareClient()

    dmarc_name = f"_dmarc.{domain}"
    dmarc_value = "v=DMARC1; p=none; rua=mailto:dmarc@{domain}".format(domain=domain)

    info(f"Creating DMARC TXT record: {dmarc_name}")
    cf.upsert_dns_record(domain, "TXT", dmarc_name, dmarc_value, proxied=False)

    ok(f"DMARC record created for '{domain}'")
    return {"status": "ok", "domain": domain, "record": dmarc_value}
