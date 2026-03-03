"""Step 3: Add custom domain to tenant and create DNS records in Cloudflare."""

import time
from log import info, ok, warn, err
from services.graph_api import GraphClient
from services.cloudflare import CloudflareClient


def run(tenant: dict, domain: str = None, **kwargs) -> dict:
    if not domain:
        err("--domain is required for add-domain step")
        return {"status": "error", "reason": "missing_domain"}

    info(f"Step 3: Add domain '{domain}' and create DNS records")

    graph = GraphClient(tenant["tenant_id"], tenant["client_id"], tenant["client_secret"])
    cf = CloudflareClient()

    # 1. Add domain to tenant
    info(f"Adding domain '{domain}' to tenant via Graph API")
    try:
        graph.post("/domains", {"id": domain})
        ok(f"Domain '{domain}' added to tenant")
    except RuntimeError as e:
        if "already exist" in str(e).lower() or "409" in str(e):
            warn(f"Domain '{domain}' already exists in tenant")
        else:
            raise

    # 2. Get verification DNS records (retry — may take a moment after domain add)
    verification_records = []
    for attempt in range(1, 6):
        info(f"Fetching verification DNS records (attempt {attempt})")
        try:
            resp = graph.get(f"/domains/{domain}/verificationDnsRecords")
            verification_records = resp.json().get("value", [])
            break
        except RuntimeError as e:
            if "404" in str(e) or "ResourceNotFound" in str(e):
                if attempt < 5:
                    info(f"Domain not ready yet, waiting {attempt * 5}s...")
                    time.sleep(attempt * 5)
                else:
                    raise
            else:
                raise

    created_records = []

    # 3. Create TXT verification record in Cloudflare
    for rec in verification_records:
        rec_type = rec.get("recordType", "")
        if rec_type == "Txt":
            txt_value = rec.get("text", "")
            info(f"Creating TXT verification record: {txt_value}")
            cf.upsert_dns_record(domain, "TXT", domain, txt_value, proxied=False)
            created_records.append({"type": "TXT", "name": domain, "value": txt_value})
            ok("TXT verification record created")

    # 4. Create MX record → domain-dashed.mail.protection.outlook.com
    mx_host = domain.replace(".", "-") + ".mail.protection.outlook.com"
    info(f"Creating MX record → {mx_host}")
    cf.upsert_dns_record(domain, "MX", domain, mx_host, priority=0, proxied=False)
    created_records.append({"type": "MX", "name": domain, "value": mx_host})
    ok("MX record created")

    # 5. Create SPF TXT record
    spf_value = "v=spf1 include:spf.protection.outlook.com -all"
    info("Creating SPF TXT record")
    # SPF is a second TXT on the root — need to avoid overwriting the verification TXT
    # Use create (not upsert) since root may already have verification TXT
    try:
        cf.create_dns_record(domain, "TXT", domain, spf_value, proxied=False)
    except RuntimeError as e:
        if "already been taken" in str(e).lower() or "81057" in str(e):
            warn("SPF record may already exist, attempting upsert")
            # List existing TXT records to find if SPF exists
            existing = cf.list_dns_records(domain, type="TXT", name=domain)
            spf_exists = any("spf" in r.get("content", "").lower() for r in existing)
            if not spf_exists:
                cf.create_dns_record(domain, "TXT", domain, spf_value, proxied=False)
        else:
            raise
    created_records.append({"type": "TXT", "name": domain, "value": spf_value})
    ok("SPF record created")

    # 6. Create autodiscover CNAME
    info("Creating autodiscover CNAME")
    cf.upsert_dns_record(domain, "CNAME", f"autodiscover.{domain}",
                         "autodiscover.outlook.com", proxied=False)
    created_records.append({"type": "CNAME", "name": f"autodiscover.{domain}",
                           "value": "autodiscover.outlook.com"})
    ok("Autodiscover CNAME created")

    ok(f"All DNS records created for '{domain}' ({len(created_records)} records)")
    return {"status": "ok", "domain": domain, "records_created": created_records}
