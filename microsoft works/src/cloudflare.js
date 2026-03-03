const log = require("./logger");
const { getAccessToken } = require("./mfa");

/**
 * Add a DNS record via Cloudflare API.
 */
async function addDnsRecord(apiKey, zoneId, type, name, content, priority, ttl = 3600) {
  const url = `https://api.cloudflare.com/client/v4/zones/${zoneId}/dns_records`;
  const body = { type, name, content, ttl };
  if (priority !== undefined && priority !== null) body.priority = priority;
  if (type === "CNAME") body.proxied = false;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  if (data.success) {
    log.success(`  DNS ${type} record added: ${name} -> ${content}`);
    return data.result;
  }

  // Check if record already exists
  const errors = data.errors || [];
  const alreadyExists = errors.some(
    (e) => e.code === 81057 || (e.message && e.message.includes("already exists"))
  );
  if (alreadyExists) {
    log.warn(`  DNS ${type} record already exists: ${name}`);
    return null;
  }

  throw new Error(`Cloudflare DNS error: ${JSON.stringify(errors)}`);
}

/**
 * Get the tenant's .onmicrosoft.com domain from Graph API.
 */
async function getTenantOnmicrosoftDomain(tenantId, clientId, clientSecret) {
  const token = await getAccessToken(tenantId, clientId, clientSecret);
  const res = await fetch("https://graph.microsoft.com/v1.0/domains", {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) {
    throw new Error(`Failed to get domains: ${res.status}`);
  }

  const data = await res.json();
  const domains = data.value || [];
  const onmicrosoft = domains.find(
    (d) => d.id && d.id.endsWith(".onmicrosoft.com") && !d.id.includes(".mail.")
  );

  if (!onmicrosoft) {
    throw new Error("Could not find .onmicrosoft.com domain");
  }

  // Return just the subdomain part (e.g. "contoso" from "contoso.onmicrosoft.com")
  return onmicrosoft.id.replace(".onmicrosoft.com", "");
}

/**
 * Add all M365 DNS records to Cloudflare for a domain.
 * Records: MX, SPF, Autodiscover CNAME, DKIM CNAME x2, DMARC TXT
 */
async function addAllM365Records(domain, apiKey, zoneId, tenantOnmicrosoft) {
  log.info(`Adding M365 DNS records for ${domain}...`);

  // Convert domain dots to dashes for DKIM (e.g. "example.com" -> "example-com")
  const domainDashes = domain.replace(/\./g, "-");

  const records = [
    // MX record
    {
      type: "MX",
      name: domain,
      content: `${domain}.mail.protection.outlook.com`,
      priority: 0,
    },
    // SPF TXT record
    {
      type: "TXT",
      name: domain,
      content: "v=spf1 include:spf.protection.outlook.com -all",
      priority: null,
    },
    // Autodiscover CNAME
    {
      type: "CNAME",
      name: `autodiscover.${domain}`,
      content: "autodiscover.outlook.com",
      priority: null,
    },
    // DKIM CNAME selector1
    {
      type: "CNAME",
      name: `selector1._domainkey.${domain}`,
      content: `selector1-${domainDashes}._domainkey.${tenantOnmicrosoft}.onmicrosoft.com`,
      priority: null,
    },
    // DKIM CNAME selector2
    {
      type: "CNAME",
      name: `selector2._domainkey.${domain}`,
      content: `selector2-${domainDashes}._domainkey.${tenantOnmicrosoft}.onmicrosoft.com`,
      priority: null,
    },
    // DMARC TXT record
    {
      type: "TXT",
      name: `_dmarc.${domain}`,
      content: `v=DMARC1; p=quarantine; rua=mailto:admin@${domain}`,
      priority: null,
    },
  ];

  let successCount = 0;
  for (const rec of records) {
    try {
      await addDnsRecord(apiKey, zoneId, rec.type, rec.name, rec.content, rec.priority);
      successCount++;
    } catch (err) {
      log.error(`  Failed to add ${rec.type} ${rec.name}: ${err.message}`);
    }
  }

  log.info(`  ${successCount}/${records.length} DNS records processed for ${domain}`);
  return successCount;
}

module.exports = {
  addDnsRecord,
  getTenantOnmicrosoftDomain,
  addAllM365Records,
};
