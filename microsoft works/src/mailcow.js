const log = require("./logger");

/**
 * Create a mailbox via Mailcow API.
 * @param {string} serverUrl - Mailcow server URL (e.g. "mail.example.com")
 * @param {string} apiKey - Mailcow API key
 * @param {object} opts - { domain, email, password, name, quota }
 */
async function createMailbox(serverUrl, apiKey, { domain, email, password, name, quota }) {
  const localPart = email.split("@")[0];
  const url = `https://${serverUrl}/api/v1/add/mailbox`;

  log.info(`  Creating mailbox: ${email} on ${serverUrl}...`);

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "X-API-Key": apiKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      local_part: localPart,
      domain: domain,
      name: name || localPart,
      password: password,
      password2: password,
      quota: quota || 256,
      active: 1,
      force_pw_update: 0,
      tls_enforce_in: 0,
      tls_enforce_out: 0,
    }),
  });

  const data = await res.json();

  // Mailcow returns an array of result objects
  if (Array.isArray(data)) {
    const result = data[0] || {};
    if (result.type === "success") {
      log.success(`  Mailbox created: ${email}`);
      return result;
    }
    if (result.type === "danger" && result.msg && result.msg.includes("already exists")) {
      log.warn(`  Mailbox already exists: ${email}`);
      return result;
    }
    if (result.type === "danger") {
      throw new Error(`Mailcow error: ${JSON.stringify(result.msg)}`);
    }
  }

  // Single object response
  if (data.type === "success") {
    log.success(`  Mailbox created: ${email}`);
    return data;
  }
  if (data.type === "danger" && data.msg && String(data.msg).includes("already exists")) {
    log.warn(`  Mailbox already exists: ${email}`);
    return data;
  }

  throw new Error(`Mailcow error: ${JSON.stringify(data)}`);
}

module.exports = { createMailbox };
