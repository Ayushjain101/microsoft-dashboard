const http = require("http");
const { spawn } = require("child_process");
const path = require("path");
const log = require("./src/logger");
const sheets = require("./src/sheets");
const mfa = require("./src/mfa");
const cloudflare = require("./src/cloudflare");
const mailcow = require("./src/mailcow");

const PORT = 8080;
const CONCURRENCY = 10;
const PROJECT_DIR = path.join(__dirname);
const SHEET_ID = "1fuwvD1G0zlTpLc5pF0bPOnEMnIBa65StVcXww3cJQ-M";
const PYTHON = "/home/ubuntu/venvs/login1/bin/python";

// Per-automation running state
const isRunning = { setup: false, mfa: false, domains: false, mailbox: false };

// ─── Parallel Pool: runs up to CONCURRENCY tasks at once ────

async function runParallel(items, limit, fn) {
  let completed = 0;
  let failed = 0;
  const total = items.length;
  const executing = new Set();

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const idx = i + 1;

    const task = (async () => {
      try {
        await fn(item, idx, total);
        completed++;
      } catch (err) {
        failed++;
        log.error(`  Parallel task ${idx}/${total} error: ${err.message}`);
      }
    })();

    executing.add(task);
    task.finally(() => executing.delete(task));

    if (executing.size >= limit) {
      await Promise.race(executing);
    }
  }

  await Promise.allSettled(executing);
  return { completed, failed, total };
}

// ─── Helper: run a Python script and stream output ──────────

function runPython(scriptName, args = []) {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(PROJECT_DIR, scriptName);
    log.info(`Running: ${PYTHON} ${scriptName} ${args.join(" ")}`);

    const proc = spawn(PYTHON, [scriptPath, ...args], {
      cwd: PROJECT_DIR,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      stdout += text;
      // Stream each line to our logger
      text.split("\n").forEach((line) => {
        if (line.trim()) log.info(`  [py] ${line}`);
      });
    });

    proc.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr += text;
      text.split("\n").forEach((line) => {
        if (line.trim()) log.warn(`  [py] ${line}`);
      });
    });

    proc.on("close", (code) => {
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new Error(`${scriptName} exited with code ${code}: ${stderr.substring(0, 200)}`));
      }
    });

    proc.on("error", (err) => {
      reject(new Error(`Failed to start ${scriptName}: ${err.message}`));
    });
  });
}

// ─── Setup: calls login1.py per row ─────────────────────────

async function processSetupRow(entry, idx, total) {
  const tag = `[${idx}/${total}] Row ${entry.row}`;
  log.info(`${tag} - ${entry.email} - STARTING`);

  try {
    const args = [
      "--email", entry.email,
      "--password", entry.password,
      "--sheet", SHEET_ID,
      "--row", String(entry.row),
    ];
    if (entry.new_password) {
      args.push("--new-password", entry.new_password);
    }

    await runPython("login1.py", args);
    log.success(`${tag} >> COMPLETE`);
  } catch (err) {
    log.error(`${tag} >> Setup failed: ${err.message}`);
    await sheets.postError(entry.row, "SETUP_FAILED");
  }
}

// ─── MFA: single row processor ──────────────────────────────

async function processMfaRow(entry, idx, total) {
  const tag = `[${idx}/${total}] Row ${entry.row}`;
  log.info(`${tag} - Tenant: ${entry.tenantId} - STARTING`);

  await sheets.updateRowStatus(entry.row, "DISABLING_MFA", "MFA");
  try {
    // Disable MFA via Graph API
    await mfa.disableAll(entry.tenantId, entry.clientId, entry.clientSecret);

    await sheets.updateRowStatus(entry.row, "MFA_DISABLED", "MFA");
    log.success(`${tag} >> MFA disabled`);
  } catch (err) {
    log.error(`${tag} >> MFA disable failed: ${err.message}`);
    await sheets.postError(entry.row, "MFA_FAILED", "MFA");
  }
}

// ─── Domains: single row processor ──────────────────────────

async function processDomainRow(entry, idx, total) {
  const tag = `[${idx}/${total}] Row ${entry.row}`;
  log.info(`${tag} - Domain: ${entry.domain} - STARTING`);

  await sheets.updateDomainRowStatus(entry.row, "ADDING_DNS");
  try {
    let tenantOnmicrosoft;
    try {
      tenantOnmicrosoft = await cloudflare.getTenantOnmicrosoftDomain(
        entry.tenantId, entry.clientId, entry.clientSecret
      );
      log.success(`${tag} >> Tenant onmicrosoft: ${tenantOnmicrosoft}`);
    } catch (err) {
      log.warn(`${tag} >> Could not get onmicrosoft domain: ${err.message}`);
      tenantOnmicrosoft = null;
    }

    if (!tenantOnmicrosoft) {
      await sheets.updateDomainRowStatus(entry.row, "FAILED: NO_ONMICROSOFT_DOMAIN");
      return;
    }

    const count = await cloudflare.addAllM365Records(
      entry.domain, entry.apiKey, entry.zoneId, tenantOnmicrosoft
    );

    await sheets.updateDomainRowStatus(entry.row, `COMPLETE (${count}/6 records)`);
    log.success(`${tag} >> DNS records added`);
  } catch (err) {
    log.error(`${tag} >> DNS failed: ${err.message}`);
    await sheets.postError(entry.row, "DNS_FAILED", "Domains");
  }
}

// ─── Mailbox: single row processor ──────────────────────────

async function processMailboxRow(entry, idx, total) {
  const tag = `[${idx}/${total}] Row ${entry.row}`;
  log.info(`${tag} - ${entry.email} - STARTING`);

  await sheets.updateMailcowRowStatus(entry.row, "CREATING_MAILBOX");
  try {
    await mailcow.createMailbox(entry.serverUrl, entry.apiKey, {
      domain: entry.domain,
      email: entry.email,
      password: entry.password,
      name: entry.name,
      quota: entry.quota,
    });
    await sheets.updateMailcowRowStatus(entry.row, "COMPLETE");
    log.success(`${tag} >> Mailbox created`);
  } catch (err) {
    log.error(`${tag} >> Mailbox failed: ${err.message}`);
    await sheets.postError(entry.row, "MAILBOX_FAILED", "Mailcow");
  }
}

// ─── Run Automations ────────────────────────────────────────

async function runSetupAutomation() {
  if (isRunning.setup) {
    log.warn("Setup automation already running, skipping...");
    return { status: "already_running" };
  }

  isRunning.setup = true;
  log.info("=== Setup Automation (login1.py — Login + App Registration) ===");
  log.info(`  Concurrency: ${CONCURRENCY}`);

  try {
    const startData = await sheets.getStatus();
    const pending = startData.pending || startData || [];
    const rows = Array.isArray(pending) ? pending : [];

    if (rows.length === 0) {
      log.warn("No pending rows found");
      isRunning.setup = false;
      return { status: "no_pending" };
    }

    log.success(`Found ${rows.length} row(s) — processing ${CONCURRENCY} at a time`);
    const result = await runParallel(rows, CONCURRENCY, processSetupRow);

    log.info(`\n${"=".repeat(50)}`);
    log.success(`SETUP DONE — ${result.completed} ok, ${result.failed} failed, ${result.total} total`);
    log.info(`${"=".repeat(50)}`);

    isRunning.setup = false;
    return { status: "complete", ...result };
  } catch (err) {
    log.error(`Setup automation error: ${err.message}`);
    isRunning.setup = false;
    return { status: "error", message: err.message };
  }
}

async function runMfaAutomation() {
  if (isRunning.mfa) {
    log.warn("MFA automation already running, skipping...");
    return { status: "already_running" };
  }

  isRunning.mfa = true;
  log.info("=== MFA Automation (Disable Security Defaults) ===");
  log.info(`  Concurrency: ${CONCURRENCY}`);

  try {
    const rows = await sheets.getSetupRowsWithCredentials();
    const entries = Array.isArray(rows) ? rows : [];

    if (entries.length === 0) {
      log.warn("No rows with credentials found for MFA disable");
      isRunning.mfa = false;
      return { status: "no_pending" };
    }

    log.success(`Found ${entries.length} tenant(s) — processing ${CONCURRENCY} at a time`);
    const result = await runParallel(entries, CONCURRENCY, processMfaRow);

    log.info(`\n${"=".repeat(50)}`);
    log.success(`MFA DONE — ${result.completed} ok, ${result.failed} failed, ${result.total} total`);
    log.info(`${"=".repeat(50)}`);

    isRunning.mfa = false;
    return { status: "complete", ...result };
  } catch (err) {
    log.error(`MFA automation error: ${err.message}`);
    isRunning.mfa = false;
    return { status: "error", message: err.message };
  }
}

async function runDomainsAutomation() {
  if (isRunning.domains) {
    log.warn("Domains automation already running, skipping...");
    return { status: "already_running" };
  }

  isRunning.domains = true;
  log.info("=== Domains Automation (Cloudflare DNS) ===");
  log.info(`  Concurrency: ${CONCURRENCY}`);

  try {
    const rows = await sheets.getDomainRows();
    const entries = Array.isArray(rows) ? rows : [];

    if (entries.length === 0) {
      log.warn("No pending domain rows found");
      isRunning.domains = false;
      return { status: "no_pending" };
    }

    log.success(`Found ${entries.length} domain(s) — processing ${CONCURRENCY} at a time`);
    const result = await runParallel(entries, CONCURRENCY, processDomainRow);

    log.info(`\n${"=".repeat(50)}`);
    log.success(`DOMAINS DONE — ${result.completed} ok, ${result.failed} failed, ${result.total} total`);
    log.info(`${"=".repeat(50)}`);

    isRunning.domains = false;
    return { status: "complete", ...result };
  } catch (err) {
    log.error(`Domains automation error: ${err.message}`);
    isRunning.domains = false;
    return { status: "error", message: err.message };
  }
}

async function runMailboxAutomation() {
  if (isRunning.mailbox) {
    log.warn("Mailbox automation already running, skipping...");
    return { status: "already_running" };
  }

  isRunning.mailbox = true;
  log.info("=== Mailbox Automation (Mailcow) ===");
  log.info(`  Concurrency: ${CONCURRENCY}`);

  try {
    const rows = await sheets.getMailcowRows();
    const entries = Array.isArray(rows) ? rows : [];

    if (entries.length === 0) {
      log.warn("No pending mailbox rows found");
      isRunning.mailbox = false;
      return { status: "no_pending" };
    }

    log.success(`Found ${entries.length} mailbox(es) — processing ${CONCURRENCY} at a time`);
    const result = await runParallel(entries, CONCURRENCY, processMailboxRow);

    log.info(`\n${"=".repeat(50)}`);
    log.success(`MAILBOX DONE — ${result.completed} ok, ${result.failed} failed, ${result.total} total`);
    log.info(`${"=".repeat(50)}`);

    isRunning.mailbox = false;
    return { status: "complete", ...result };
  } catch (err) {
    log.error(`Mailbox automation error: ${err.message}`);
    isRunning.mailbox = false;
    return { status: "error", message: err.message };
  }
}

// ─── HTTP Server ──────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(200);
    res.end();
    return;
  }

  const json = (code, data) => {
    res.writeHead(code, { "Content-Type": "application/json" });
    res.end(JSON.stringify(data));
  };

  if (req.url === "/health" || req.url === "/") {
    json(200, { status: "ok", running: isRunning });
    return;
  }

  if (req.url === "/status") {
    json(200, { running: isRunning });
    return;
  }

  // Button 1: Run Setup (login1.py)
  if (req.url === "/start" || req.url === "/start-setup") {
    log.info("Trigger received: Setup");
    json(200, { status: "started", automation: "setup" });
    runSetupAutomation().catch((err) => log.error(`Setup error: ${err.message}`));
    return;
  }

  // Button 2: Disable MFA
  if (req.url === "/start-mfa") {
    log.info("Trigger received: MFA");
    json(200, { status: "started", automation: "mfa" });
    runMfaAutomation().catch((err) => log.error(`MFA error: ${err.message}`));
    return;
  }

  // Button 3: Add Domains
  if (req.url === "/start-domains") {
    log.info("Trigger received: Domains");
    json(200, { status: "started", automation: "domains" });
    runDomainsAutomation().catch((err) => log.error(`Domains error: ${err.message}`));
    return;
  }

  // Button 4: Create Mailboxes
  if (req.url === "/start-mailbox") {
    log.info("Trigger received: Mailbox");
    json(200, { status: "started", automation: "mailbox" });
    runMailboxAutomation().catch((err) => log.error(`Mailbox error: ${err.message}`));
    return;
  }

  json(404, { error: "not found" });
});

server.listen(PORT, "0.0.0.0", () => {
  log.info(`Server listening on http://0.0.0.0:${PORT}`);
  log.info(`Concurrency: ${CONCURRENCY} parallel tasks per automation`);
  log.info(`Setup uses: ${PYTHON} login1.py`);
  log.info("Routes: /start-setup, /start-mfa, /start-domains, /start-mailbox, /status");
  log.info("Waiting for trigger from Apps Script...");
});
