/**
 * Microsoft Tenant Automation via Google Apps Script
 * ===================================================
 * 
 * Reads configuration from Google Sheets
 * Calls Microsoft Graph API directly
 * Logs results back to Sheets
 * 
 * Setup:
 * 1. Create Google Sheet with tabs: Settings, Users, Domains, Mailboxes, Logs
 * 2. Fill in Settings tab with tenant credentials
 * 3. Populate Users, Domains, Mailboxes tabs
 * 4. Run menu: Custom > Run Tenant Automation
 * 5. Deploy as web app (Deploy > New Deployment > Web App)
 */

// ─── Global Config ──────────────────────────────────────────
// CHANGE THIS TO YOUR ACTUAL SHEET ID
const SHEET_ID = "1fuwvD1G0zlTpLc5pF0bPOnEMnIBa65StVcXww3cJQ-M";
const SETTINGS_SHEET = "Settings";
const USERS_SHEET = "Users";
const DOMAINS_SHEET = "Domains";
const MAILBOXES_SHEET = "Mailboxes";
const LOGS_SHEET = "Logs";

/**
 * Required Settings Tab Rows (Column A = Key, Column B = Value):
 * Row 1: Headers (Key | Value)
 * Row 2+: 
 *   TENANT_ID | Your-Tenant-ID
 *   CLIENT_ID | Your-Client-ID
 *   CLIENT_SECRET | Your-Client-Secret
 *   ADMIN_EMAIL | admin@yourdomain.com (for MFA removal + licensing)
 *   CLOUDFLARE_EMAIL | your@cloudflare.com (for DNS automation)
 *   CLOUDFLARE_API_KEY | Your-API-Token (for DNS automation)
 */

const GRAPH_API_URL = "https://graph.microsoft.com/v1.0";
const TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token";

// ─── Menu Setup ────────────────────────────────────────────
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu("Custom")
    .addItem("Run Tenant Automation", "runAutomation")
    .addItem("Clear Logs", "clearLogs")
    .addItem("Get Token Info", "debugToken")
    .addToUi();
}

// ─── Logging ────────────────────────────────────────────────
function log(level, message) {
  const timestamp = new Date().toLocaleString();
  const logEntry = `[${timestamp}] ${level}: ${message}`;
  console.log(logEntry);
  
  // Also append to Logs sheet
  const logsSheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(LOGS_SHEET);
  if (logsSheet) {
    logsSheet.appendRow([timestamp, level, message]);
  }
}

function logInfo(msg) { log("INFO", msg); }
function logOk(msg) { log("OK", msg); }
function logWarn(msg) { log("WARN", msg); }
function logErr(msg) { log("ERROR", msg); }

function clearLogs() {
  const logsSheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(LOGS_SHEET);
  if (logsSheet) {
    logsSheet.clearContents();
    logsSheet.appendRow(["Timestamp", "Level", "Message"]);
    logOk("Logs cleared");
  }
}

// ─── Settings Management ────────────────────────────────────
function getSettings() {
  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(SETTINGS_SHEET);
  const data = sheet.getDataRange().getValues();
  
  const settings = {};
  for (let i = 1; i < data.length; i++) { // Skip header
    const key = data[i][0];
    const value = data[i][1];
    if (key && value) {
      settings[key] = value;
    }
  }
  
  return settings;
}

function validateSettings(settings) {
  const required = ["TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"];
  for (const field of required) {
    if (!settings[field]) {
      logErr(`Missing setting: ${field}`);
      return false;
    }
  }
  return true;
}

// ─── Microsoft Graph API ────────────────────────────────────
function getAccessToken(tenantId, clientId, clientSecret) {
  logInfo("Fetching access token...");
  
  const url = TOKEN_URL_TEMPLATE.replace("{tenant}", tenantId);
  const payload = {
    grant_type: "client_credentials",
    client_id: clientId,
    client_secret: clientSecret,
    scope: "https://graph.microsoft.com/.default"
  };
  
  const options = {
    method: "post",
    payload: payload,
    muteHttpExceptions: true,
    headers: {
      "Content-Type": "application/x-www-form-urlencoded"
    }
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const result = JSON.parse(response.getContentText());
    
    if (response.getResponseCode() === 200) {
      logOk("Access token acquired");
      return result.access_token;
    } else {
      const errorMsg = result.error_description || response.getContentText();
      logErr(`Token request failed: ${errorMsg}`);
      return null;
    }
  } catch (e) {
    logErr(`Token fetch error: ${e.message}`);
    return null;
  }
}

function graphGet(token, endpoint) {
  const url = `${GRAPH_API_URL}/${endpoint}`;
  const options = {
    method: "get",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    muteHttpExceptions: true
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const result = JSON.parse(response.getContentText());
    
    if (response.getResponseCode() >= 200 && response.getResponseCode() < 300) {
      return { success: true, data: result };
    } else {
      return { success: false, error: result.error?.message || response.getContentText() };
    }
  } catch (e) {
    return { success: false, error: e.message };
  }
}

function graphPatch(token, endpoint, body) {
  const url = `${GRAPH_API_URL}/${endpoint}`;
  const options = {
    method: "patch",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const statusCode = response.getResponseCode();
    
    if (statusCode >= 200 && statusCode < 300) {
      let result = {};
      try {
        result = JSON.parse(response.getContentText());
      } catch (e) {
        // 204 No Content is okay
      }
      return { success: true, data: result };
    } else {
      const result = JSON.parse(response.getContentText());
      return { success: false, error: result.error?.message || response.getContentText() };
    }
  } catch (e) {
    return { success: false, error: e.message };
  }
}

function graphPost(token, endpoint, body) {
  const url = `${GRAPH_API_URL}/${endpoint}`;
  const options = {
    method: "post",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const statusCode = response.getResponseCode();
    
    if (statusCode >= 200 && statusCode < 300) {
      const contentText = response.getContentText();
      let result = {};
      try {
        result = JSON.parse(contentText);
      } catch (e) {
        // 204 No Content is okay
      }
      return { success: true, data: result };
    } else {
      const contentText = response.getContentText();
      let errorMsg = "Unknown error";
      try {
        const result = JSON.parse(contentText);
        errorMsg = result.error?.message || contentText;
      } catch (e) {
        errorMsg = contentText;
      }
      return { success: false, error: errorMsg };
    }
  } catch (e) {
    return { success: false, error: e.message };
  }
}

// ─── Phase 1: Security Setup (FULL AUTOMATION) ─────────────────
function setupSecurity(token) {
  logInfo("━━━ PHASE 1: Security Setup (Full Automation) ━━━");
  
  let success = true;
  const settings = getSettings();
  
  // 1.1: Disable Security Defaults
  logInfo("  1.1: Disabling Security Defaults...");
  let result = graphPatch(token, "policies/identitySecurityDefaultsEnforcementPolicy", {
    isEnabled: false
  });
  
  if (result.success) {
    logOk("  ✓ Security Defaults DISABLED");
  } else {
    logErr(`  ✗ Failed: ${result.error}`);
    success = false;
  }
  
  // 1.2: Disable MFA Registration Campaign
  logInfo("  1.2: Disabling MFA registration campaign...");
  result = graphPatch(token, "policies/authenticationMethodsPolicy", {
    registrationCampaign: {
      enforceRegistrationAfterAllowListExpires: false,
      includeTarget: {
        targetType: "group",
        id: "00000000-0000-0000-0000-000000000000"
      }
    }
  });
  
  if (result.success) {
    logOk("  ✓ MFA registration campaign DISABLED");
  } else {
    logWarn(`  ⚠ MFA campaign: ${result.error}`);
  }
  
  // 1.3: Disable System-Preferred MFA
  logInfo("  1.3: Disabling system-preferred MFA...");
  result = graphPatch(token, "policies/authenticationMethodsPolicy", {
    systemPreferredAuthenticationMethods: []
  });
  
  if (result.success) {
    logOk("  ✓ System-preferred MFA DISABLED");
  } else {
    logWarn(`  ⚠ System MFA: ${result.error}`);
  }
  
  // 1.4: Delete Admin User's MFA
  logInfo("  1.4: Removing admin user MFA...");
  const adminEmail = settings.ADMIN_EMAIL || settings.ADMIN_USER_EMAIL;
  
  if (adminEmail) {
    logInfo(`      Admin email: ${adminEmail}`);
    const userResult = graphGet(token, `users?$filter=userPrincipalName eq '${adminEmail}'`);
    
    if (userResult.success && userResult.data.value && userResult.data.value.length > 0) {
      const adminUserId = userResult.data.value[0].id;
      logInfo(`      Admin user ID found, removing MFA methods...`);
      
      const authMethodsResult = graphGet(token, `users/${adminUserId}/authentication/methods`);
      
      if (authMethodsResult.success && authMethodsResult.data.value) {
        let removedCount = 0;
        for (const method of authMethodsResult.data.value) {
          const methodId = method.id;
          const methodType = method['@odata.type'] || 'unknown';
          
          if (methodType.includes('password')) continue;
          
          const deleteResult = graphDelete(token, `users/${adminUserId}/authentication/methods/${methodId}`);
          if (deleteResult.success) {
            removedCount++;
            logInfo(`        ✓ Removed: ${methodType}`);
          } else {
            logWarn(`        ⚠ Could not remove ${methodType}`);
          }
          Utilities.sleep(200);
        }
        logOk(`  ✓ Admin MFA removed (${removedCount} methods deleted)`);
      } else {
        logWarn(`  ⚠ Could not retrieve MFA methods`);
      }
    } else {
      logWarn(`  ⚠ Admin user not found: ${adminEmail}`);
    }
  } else {
    logWarn(`  ⚠ ADMIN_EMAIL not in Settings. Add "ADMIN_EMAIL" row with value like: admin@yourdomain.com`);
  }
  
  // 1.5: Enable SMTP AUTH (requires manual step — Graph API limitation)
  logInfo("  1.5: SMTP AUTH configuration...");
  logWarn(`  ⚠ SMTP AUTH requires manual step (Graph API limitation)`);
  logInfo(`      TODO: admin.exchange.microsoft.com > Settings > Mail Flow > Uncheck "Turn off SMTP AUTH"`);
  
  // 1.6: Assign License to Admin User
  logInfo("  1.6: Assigning license to admin user...");
  
  if (adminEmail) {
    const userResult = graphGet(token, `users?$filter=userPrincipalName eq '${adminEmail}'`);
    
    if (userResult.success && userResult.data.value && userResult.data.value.length > 0) {
      const adminUserId = userResult.data.value[0].id;
      
      const skusResult = graphGet(token, "subscribedSkus");
      if (skusResult.success && skusResult.data.value && skusResult.data.value.length > 0) {
        const sku = skusResult.data.value[0];
        
        const licenseBody = {
          addLicenses: [{ skuId: sku.skuId }],
          removeLicenses: []
        };
        
        const licenseResult = graphPost(token, `users/${adminUserId}/assignLicense`, licenseBody);
        
        if (licenseResult.success) {
          logOk(`  ✓ License assigned to admin (${sku.skuPartNumber})`);
        } else {
          if (licenseResult.error.includes("already")) {
            logOk(`  ✓ Admin already has license`);
          } else {
            logWarn(`  ⚠ License assignment: ${licenseResult.error}`);
          }
        }
      } else {
        logWarn(`  ⚠ No licenses available to assign`);
      }
    } else {
      logWarn(`  ⚠ Could not find admin user`);
    }
  }
  
  logOk("✓ Phase 1 complete");
  return success;
}

// ─── Cloudflare DNS API ────────────────────────────────────
function cloudflareApiCall(method, endpoint, data, cfEmail, cfApiKey) {
  const url = `https://api.cloudflare.com/client/v4${endpoint}`;
  
  const options = {
    method: method,
    headers: {
      "X-Auth-Email": cfEmail,
      "X-Auth-Key": cfApiKey,
      "Content-Type": "application/json"
    },
    muteHttpExceptions: true
  };
  
  if (data) {
    options.payload = JSON.stringify(data);
  }
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const result = JSON.parse(response.getContentText());
    
    if (result.success) {
      return { success: true, data: result.result };
    } else {
      const errorMsg = result.errors ? result.errors[0]?.message : "Unknown error";
      return { success: false, error: errorMsg };
    }
  } catch (e) {
    return { success: false, error: e.message };
  }
}

function addDnsRecord(zoneId, domainName, recordType, recordName, recordValue, cfEmail, cfApiKey, ttl = 3600) {
  logInfo(`    Adding ${recordType} record: ${recordName} → ${recordValue}`);
  
  const result = cloudflareApiCall("POST", `/zones/${zoneId}/dns_records`, {
    type: recordType,
    name: recordName,
    content: recordValue,
    ttl: ttl,
    proxied: false
  }, cfEmail, cfApiKey);
  
  if (result.success) {
    logOk(`    ✓ ${recordType} record added`);
    return true;
  } else {
    logWarn(`    ⚠ ${recordType} failed: ${result.error}`);
    return false;
  }
}

// ─── Phase 2: Domain Management ─────────────────────────────
function setupDomains(token) {
  logInfo("━━━ PHASE 2: Domain Management ━━━");
  
  const settings = getSettings();
  const cfEmail = settings.CLOUDFLARE_EMAIL;
  const cfApiKey = settings.CLOUDFLARE_API_KEY;
  
  if (!cfEmail || !cfApiKey) {
    logWarn("  ⚠ Cloudflare credentials not in Settings. Skipping DNS automation.");
  }
  
  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(DOMAINS_SHEET);
  const data = sheet.getDataRange().getValues();
  
  let count = 0;
  
  for (let i = 1; i < data.length; i++) { // Skip header
    const domain = data[i][0]?.trim();
    const enableDkim = data[i][1];
    const addDmarc = data[i][2];
    const cfZoneId = data[i][3]?.trim();
    const configureMx = data[i][4];
    const configureSsf = data[i][5];
    const configureDkim = data[i][6];
    const configureDmrc = data[i][7];
    
    if (!domain) continue;
    
    logInfo(`  2.1: Processing domain '${domain}'...`);
    
    let result = graphPost(token, "domains", {
      id: domain
    });
    
    if (result.success) {
      logOk(`  ✓ Domain '${domain}' added to Microsoft`);
      count++;
      
      // Verify domain
      logInfo(`  2.2: Verifying domain '${domain}'...`);
      result = graphPost(token, `domains/${domain}/verify`, {});
      
      if (result.success) {
        logOk(`  ✓ Domain verified in Microsoft`);
      } else {
        logWarn(`  ⚠ Verification pending: ${result.error}`);
      }
      
      // Enable DKIM in Microsoft
      if (enableDkim) {
        logInfo(`  2.3: Enabling DKIM in Microsoft...`);
        result = graphPost(token, "domainDnsRecords/createDkim", {
          domainId: domain
        });
        
        if (result.success) {
          logOk(`  ✓ DKIM enabled in Microsoft`);
        } else {
          logWarn(`  ⚠ DKIM enable: ${result.error}`);
        }
      }
      
      // Configure Cloudflare DNS records
      if (cfEmail && cfApiKey && cfZoneId) {
        logInfo(`  2.4: Configuring Cloudflare DNS records...`);
        
        // MX Records
        if (configureMx) {
          logInfo(`  📧 Adding MX records for Exchange...`);
          addDnsRecord(cfZoneId, domain, "MX", domain, "10 yourdomain-com.mail.protection.outlook.com", cfEmail, cfApiKey, 3600);
        }
        
        // SPF Record
        if (configureSsf) {
          logInfo(`  🔐 Adding SPF record...`);
          addDnsRecord(cfZoneId, domain, "TXT", domain, "v=spf1 include:spf.protection.outlook.com ~all", cfEmail, cfApiKey, 3600);
        }
        
        // DKIM Record (placeholder — user will need to add actual DKIM key from Microsoft)
        if (configureDkim) {
          logInfo(`  🔑 DKIM record setup (manual key needed from Microsoft)`);
          logInfo(`     Note: Get DKIM public key from Microsoft 365 admin center`);
          logInfo(`     Then create CNAME: selector1._domainkey.${domain} → selector1-${domain.replace(/\./g, '-')}.dkim.protection.outlook.com`);
        }
        
        // DMARC Record
        if (configureDmrc) {
          logInfo(`  🛡️ Adding DMARC record...`);
          const dmarcRecord = `v=DMARC1; p=quarantine; rua=mailto:postmaster@${domain}; ruf=mailto:postmaster@${domain}; fo=1`;
          addDnsRecord(cfZoneId, domain, "TXT", `_dmarc.${domain}`, dmarcRecord, cfEmail, cfApiKey, 3600);
        }
        
      } else if (cfZoneId) {
        logWarn(`  ⚠ Cloudflare credentials missing. Cannot configure DNS.`);
      } else {
        logInfo(`  ℹ️ No Cloudflare Zone ID provided. DNS records not added.`);
      }
      
    } else if (result.error.includes("already exists")) {
      logWarn(`  ⚠ Domain '${domain}' already exists in Microsoft`);
      count++;
    } else {
      logErr(`  ✗ Failed: ${result.error}`);
    }
    
    Utilities.sleep(500);
  }
  
  logOk(`✓ Domain setup complete (${count} domains)`);
  return true;
}

// ─── Phase 3: User Creation ─────────────────────────────────
function setupUsers(token) {
  logInfo("━━━ PHASE 3: User Creation & Licensing ━━━");
  
  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(USERS_SHEET);
  const data = sheet.getDataRange().getValues();
  
  let created = 0;
  let assigned = 0;
  
  for (let i = 1; i < data.length; i++) { // Skip header
    const firstName = data[i][0]?.trim();
    const lastName = data[i][1]?.trim();
    const email = data[i][2]?.trim();
    const password = data[i][3]?.trim();
    const assignLicense = data[i][4];
    
    if (!firstName || !lastName || !email || !password) continue;
    
    logInfo(`  3.1: Creating user '${email}'...`);
    
    const userBody = {
      accountEnabled: true,
      displayName: `${firstName} ${lastName}`,
      mailNickname: email.split("@")[0],
      userPrincipalName: email,
      passwordProfile: {
        forceChangePasswordNextSignIn: false,
        password: password
      },
      givenName: firstName,
      surname: lastName
    };
    
    let result = graphPost(token, "users", userBody);
    
    if (result.success) {
      logOk(`  ✓ User '${email}' created`);
      created++;
      
      const userId = result.data.id;
      
      // Assign license
      if (assignLicense && userId) {
        logInfo(`  3.2: Assigning license...`);
        
        // Get first available license
        const skusResult = graphGet(token, "subscribedSkus");
        if (skusResult.success && skusResult.data.value && skusResult.data.value.length > 0) {
          const sku = skusResult.data.value[0];
          const licenseBody = {
            addLicenses: [{ skuId: sku.skuId }],
            removeLicenses: []
          };
          
          const licenseResult = graphPost(token, `users/${userId}/assignLicense`, licenseBody);
          if (licenseResult.success) {
            logOk(`  ✓ License assigned (${sku.skuPartNumber})`);
            assigned++;
          } else {
            logWarn(`  ⚠ License assignment: ${licenseResult.error}`);
          }
        } else {
          logWarn(`  ⚠ No licenses available`);
        }
      }
      
    } else if (result.error.includes("already exists")) {
      logWarn(`  ⚠ User '${email}' already exists`);
    } else {
      logErr(`  ✗ Failed: ${result.error}`);
    }
    
    // Rate limiting
    Utilities.sleep(500);
  }
  
  logOk(`✓ User setup complete (${created} created, ${assigned} licensed)`);
  return true;
}

// ─── Phase 4: Mailbox Setup ─────────────────────────────────
function setupMailboxes(token) {
  logInfo("━━━ PHASE 4: Room Mailbox Setup ━━━");
  
  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(MAILBOXES_SHEET);
  const data = sheet.getDataRange().getValues();
  
  let count = 0;
  
  for (let i = 1; i < data.length; i++) { // Skip header
    const name = data[i][0]?.trim();
    const email = data[i][1]?.trim();
    const type = data[i][2]?.trim() || "SharedMailbox";
    
    if (!name || !email) continue;
    
    logInfo(`  4.1: Creating mailbox '${email}'...`);
    
    const mailboxBody = {
      displayName: name,
      mailNickname: email.split("@")[0],
      mail: email,
      resourceBehaviorOptions: ["CalendarMemberReadOnly"],
      resourceDisplayName: name,
      resourceType: type.includes("Room") ? "Room" : "Equipment"
    };
    
    let result = graphPost(token, "resources/rooms", mailboxBody);
    
    if (result.success) {
      logOk(`  ✓ Mailbox '${email}' created`);
      count++;
    } else if (result.error.includes("already exists")) {
      logWarn(`  ⚠ Mailbox '${email}' already exists`);
    } else {
      logErr(`  ✗ Failed: ${result.error}`);
    }
    
    Utilities.sleep(500);
  }
  
  logOk(`✓ Mailbox setup complete (${count} created)`);
  return true;
}

// ─── Main Automation ────────────────────────────────────────
function runAutomation() {
  logInfo("╔════════════════════════════════════════════════════════╗");
  logInfo("║  Microsoft Tenant Automation — Apps Script Edition     ║");
  logInfo("╚════════════════════════════════════════════════════════╝");
  logInfo("");
  
  // Get settings
  const settings = getSettings();
  if (!validateSettings(settings)) {
    logErr("Automation aborted: invalid settings");
    return;
  }
  
  logInfo(`Tenant ID: ${settings.TENANT_ID}`);
  logInfo(`Client ID: ${settings.CLIENT_ID}`);
  logInfo("");
  
  // Get token
  const token = getAccessToken(settings.TENANT_ID, settings.CLIENT_ID, settings.CLIENT_SECRET);
  if (!token) {
    logErr("Automation aborted: could not acquire token");
    return;
  }
  
  logInfo("");
  
  // Run phases
  setupSecurity(token);
  logInfo("");
  
  setupDomains(token);
  logInfo("");
  
  setupUsers(token);
  logInfo("");
  
  setupMailboxes(token);
  logInfo("");
  
  logInfo("╔════════════════════════════════════════════════════════╗");
  logOk("║              AUTOMATION COMPLETE ✓                      ║");
  logInfo("╚════════════════════════════════════════════════════════╝");
}

// ─── Debug Helper ───────────────────────────────────────────
function debugToken() {
  const settings = getSettings();
  if (!validateSettings(settings)) {
    logErr("Invalid settings");
    return;
  }
  
  const token = getAccessToken(settings.TENANT_ID, settings.CLIENT_ID, settings.CLIENT_SECRET);
  if (token) {
    logOk("Token acquired successfully");
    logInfo(`Token length: ${token.length} chars`);
  }
}

// ─── Web App Entry Points ────────────────────────────────────
function doGet(e) {
  const action = e.parameter.action || "status";
  
  if (action === "run") {
    runAutomation();
    return HtmlService.createHtmlOutput("<h2>✓ Automation started. Check the Logs sheet in your Google Sheet.</h2><p><a href='javascript:history.back()'>Go back</a></p>");
  } else if (action === "clear-logs") {
    clearLogs();
    return HtmlService.createHtmlOutput("<h2>✓ Logs cleared</h2><p><a href='javascript:history.back()'>Go back</a></p>");
  } else if (action === "status") {
    return HtmlService.createHtmlOutput(`
      <h2>Tenant Automation Web App</h2>
      <p>Click a button below to run actions:</p>
      <ul>
        <li><a href="?action=run" style="padding: 10px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px;">▶ Run Automation</a></li>
        <li><a href="?action=clear-logs" style="padding: 10px; background: #FF9800; color: white; text-decoration: none; border-radius: 5px;">🗑 Clear Logs</a></li>
      </ul>
      <p><a href="https://docs.google.com/spreadsheets/d/1fuwvD1G0zlTpLc5pF0bPOnEMnIBa65StVcXww3cJQ-M/edit" target="_blank">📊 Open Google Sheet</a></p>
    `);
  }
}

function doPost(e) {
  const action = e.parameter.action || "run";
  
  if (action === "run") {
    runAutomation();
    return ContentService.createTextOutput(JSON.stringify({ status: "started", message: "Automation running. Check Logs sheet." })).setMimeType(ContentService.MimeType.JSON);
  }
  
  return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "Unknown action" })).setMimeType(ContentService.MimeType.JSON);
}

