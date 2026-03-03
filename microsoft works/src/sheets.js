const config = require("./config");
const log = require("./logger");

// ─── Existing functions (Setup tab) ────────────────────────

async function getStatus() {
  const res = await fetch(config.appsScriptUrl, { redirect: "follow" });
  if (!res.ok) throw new Error(`GET failed: ${res.status}`);
  return res.json();
}

async function postCredentials(row, tenantId, clientId, clientSecret) {
  log.info(`Posting credentials to row ${row}...`);
  const body = JSON.stringify({
    action: "credentials",
    row,
    tenantId,
    clientId,
    clientSecret,
  });

  const res = await fetch(config.appsScriptUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    redirect: "follow",
  });

  try {
    const data = await res.json();
    log.success(`Credentials posted to row ${row}`);
    return data;
  } catch {
    log.info("Response was not JSON (redirect), but POST was processed");
    return { status: "ok" };
  }
}

async function updateRowStatus(row, status, tab) {
  const body = JSON.stringify({ action: "rowStatus", row, status, tab: tab || "Setting" });
  const res = await fetch(config.appsScriptUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    redirect: "follow",
  });
  try { return await res.json(); } catch { return { status: "ok" }; }
}

async function postError(row, message, tab) {
  log.info(`Posting error to row ${row}: ${message}`);
  const body = JSON.stringify({ action: "error", row, message, tab: tab || "Setting" });

  const res = await fetch(config.appsScriptUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    redirect: "follow",
  });

  try {
    return await res.json();
  } catch {
    return { status: "ok" };
  }
}

async function updateStatus(status) {
  log.info(`Updating sheet status to: ${status}`);
  const body = JSON.stringify({ action: "status", status });

  const res = await fetch(config.appsScriptUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    redirect: "follow",
  });

  try {
    return await res.json();
  } catch {
    return { status: "ok" };
  }
}

async function updatePassword(row, password) {
  log.info(`Updating password in sheet for row ${row} (after password change)`);
  const body = JSON.stringify({ action: "updatePassword", row, password });
  const res = await fetch(config.appsScriptUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    redirect: "follow",
  });
  try { return await res.json(); } catch { return { status: "ok" }; }
}

// ─── New functions (multi-tab support) ─────────────────────

async function getSetupRows() {
  const url = `${config.appsScriptUrl}?action=getSetupRows`;
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`getSetupRows failed: ${res.status}`);
  return res.json();
}

async function getSetupRowsWithCredentials() {
  const url = `${config.appsScriptUrl}?action=getSetupRowsWithCredentials`;
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`getSetupRowsWithCredentials failed: ${res.status}`);
  return res.json();
}

async function getDomainRows() {
  const url = `${config.appsScriptUrl}?action=getDomainRows`;
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`getDomainRows failed: ${res.status}`);
  return res.json();
}

async function getMailcowRows() {
  const url = `${config.appsScriptUrl}?action=getMailcowRows`;
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`getMailcowRows failed: ${res.status}`);
  return res.json();
}

async function updateDomainRowStatus(row, status) {
  return updateRowStatus(row, status, "Domains");
}

async function updateMailcowRowStatus(row, status) {
  return updateRowStatus(row, status, "Mailcow");
}

async function copyCredentialsToDomains(tenantId, clientId, clientSecret) {
  log.info("Copying credentials to Domains tab...");
  const body = JSON.stringify({
    action: "copyCredentialsToDomains",
    tenantId,
    clientId,
    clientSecret,
  });

  const res = await fetch(config.appsScriptUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    redirect: "follow",
  });

  try {
    const data = await res.json();
    log.success("Credentials copied to Domains tab");
    return data;
  } catch {
    return { status: "ok" };
  }
}

module.exports = {
  getStatus,
  postCredentials,
  postError,
  updateStatus,
  updateRowStatus,
  updatePassword,
  getSetupRows,
  getSetupRowsWithCredentials,
  getDomainRows,
  getMailcowRows,
  updateDomainRowStatus,
  updateMailcowRowStatus,
  copyCredentialsToDomains,
};
