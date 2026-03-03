const { execFile, spawn } = require("child_process");
const log = require("./logger");
const { browserLogin } = require("./browser-login");

// Azure CLI path — auto-detect Windows or Linux
const isWindows = process.platform === "win32";
const AZ = isWindows
  ? '"C:\\Program Files (x86)\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.cmd"'
  : "az";

// Microsoft Graph API id
const GRAPH_API = "00000003-0000-0000-c000-000000000000";
// Office 365 Exchange Online API id
const EXCHANGE_API = "00000002-0000-0ff1-ce00-000000000000";

// Permission GUIDs
const PERMISSIONS = {
  // Application (Role) permissions
  graphUserReadWriteAll: "741f803b-c850-494e-b5df-cde7c675a1ca",         // User.ReadWrite.All
  graphUserAuthMethodReadWriteAll: "50483e42-d915-4231-9639-7fdb7fd190e5", // UserAuthenticationMethod.ReadWrite.All
  graphMailSend: "b633e1c5-b582-4048-a93e-9f11b44c7e96",                  // Mail.Send
  // Delegated (Scope) permission
  graphSmtpSend: "258f6531-6087-4cc4-bb90-092c5fb3ed3f",                  // SMTP.Send (Delegated)
  // Exchange Application (Role) permission
  exchangeFullAccessAsApp: "dc890d15-9560-4a4c-9b7f-a736ec74ec40",        // full_access_as_app
};

function azCommand(args) {
  return new Promise((resolve, reject) => {
    log.info(`az ${args.join(" ")}`);
    // shell: true is required on Windows to execute .cmd files via execFile
    execFile(AZ, args, { maxBuffer: 10 * 1024 * 1024, shell: true }, (err, stdout, stderr) => {
      if (err) {
        const msg = stderr || err.message;
        reject(new Error(`az command failed: ${msg}`));
        return;
      }
      resolve(stdout.trim());
    });
  });
}

async function login(email, password, newPassword, mfaSecret) {
  log.info(`Logging in as ${email} via device code + Selenium...`);

  // Start az login --use-device-code in background and capture the device code
  const deviceCode = await new Promise((resolve, reject) => {
    let proc;
    if (isWindows) {
      const fullCmd = '"C:\\Program Files (x86)\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.cmd" login --use-device-code --allow-no-subscriptions';
      proc = spawn("cmd.exe", ["/c", fullCmd], { windowsVerbatimArguments: true });
    } else {
      proc = spawn("az", ["login", "--use-device-code", "--allow-no-subscriptions"]);
    }

    let stderr = "";
    let resolved = false;

    proc.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr += text;
      log.info(`az: ${text.trim()}`);

      // Extract device code from: "enter the code XXXXXXXX to authenticate"
      const match = text.match(/enter the code\s+(\S+)\s+to authenticate/i);
      if (match && !resolved) {
        resolved = true;
        resolve({ code: match[1], proc });
      }
    });

    proc.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      log.info(`az: ${text.trim()}`);
    });

    proc.on("error", (err) => {
      if (!resolved) reject(new Error(`az login failed to start: ${err.message}`));
    });

    // Timeout after 30s if no device code appears
    setTimeout(() => {
      if (!resolved) reject(new Error(`No device code received. stderr: ${stderr}`));
    }, 30_000);
  });

  log.success(`Got device code: ${deviceCode.code}`);

  // Use Selenium to complete the login in the browser
  const result = await browserLogin(email, password, newPassword, deviceCode.code, mfaSecret);

  // Wait for az login process to complete
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      deviceCode.proc.kill();
      reject(new Error("az login timed out after device code was entered"));
    }, 60_000);

    deviceCode.proc.on("close", (exitCode) => {
      clearTimeout(timer);
      if (exitCode === 0) {
        log.success(`Azure login successful for ${email}`);
        resolve();
      } else {
        reject(new Error(`az login exited with code ${exitCode}`));
      }
    });
  });

  return { passwordChanged: result.passwordChanged };
}

async function validateLogin() {
  const raw = await azCommand(["account", "show", "--allow-no-subscriptions", "-o", "json"]);
  if (!raw) {
    // Fallback: try account list
    const listRaw = await azCommand(["account", "list", "--allow-no-subscriptions", "-o", "json"]);
    const accounts = JSON.parse(listRaw || "[]");
    if (accounts.length > 0) {
      log.success(`Logged in to tenant: ${accounts[0].tenantId}`);
      return accounts[0];
    }
    throw new Error("No Azure accounts found after login");
  }
  const account = JSON.parse(raw);
  log.success(`Logged in to tenant: ${account.tenantId}`);
  return account;
}

async function createAppRegistration(name) {
  log.info(`Creating App Registration: ${name}`);
  const raw = await azCommand([
    "ad", "app", "create",
    "--display-name", name,
    "--sign-in-audience", "AzureADMyOrg",
    "-o", "json",
  ]);
  const app = JSON.parse(raw);
  log.success(`App created — appId: ${app.appId}, objectId: ${app.id}`);
  return app;
}

async function addPermissions(appId) {
  log.info("Adding API permissions (sequential to avoid conflicts)...");

  // 1. Graph: User.ReadWrite.All (Role)
  await azCommand([
    "ad", "app", "permission", "add",
    "--id", appId,
    "--api", GRAPH_API,
    "--api-permissions", `${PERMISSIONS.graphUserReadWriteAll}=Role`,
  ]);
  log.success("Added Graph User.ReadWrite.All (Application)");

  // 2. Graph: UserAuthenticationMethod.ReadWrite.All (Role)
  await azCommand([
    "ad", "app", "permission", "add",
    "--id", appId,
    "--api", GRAPH_API,
    "--api-permissions", `${PERMISSIONS.graphUserAuthMethodReadWriteAll}=Role`,
  ]);
  log.success("Added Graph UserAuthenticationMethod.ReadWrite.All (Application)");

  // 3. Graph: Mail.Send (Role)
  await azCommand([
    "ad", "app", "permission", "add",
    "--id", appId,
    "--api", GRAPH_API,
    "--api-permissions", `${PERMISSIONS.graphMailSend}=Role`,
  ]);
  log.success("Added Graph Mail.Send (Application)");

  // 4. Graph: SMTP.Send (Delegated/Scope)
  await azCommand([
    "ad", "app", "permission", "add",
    "--id", appId,
    "--api", GRAPH_API,
    "--api-permissions", `${PERMISSIONS.graphSmtpSend}=Scope`,
  ]);
  log.success("Added Graph SMTP.Send (Delegated)");

  // 5. Exchange: full_access_as_app (Role)
  await azCommand([
    "ad", "app", "permission", "add",
    "--id", appId,
    "--api", EXCHANGE_API,
    "--api-permissions", `${PERMISSIONS.exchangeFullAccessAsApp}=Role`,
  ]);
  log.success("Added Exchange full_access_as_app (Application)");
}

async function grantAdminConsent(appId) {
  log.info("Attempting admin consent (best-effort)...");
  try {
    await azCommand(["ad", "app", "permission", "admin-consent", "--id", appId]);
    log.success("Admin consent granted");
  } catch (err) {
    log.warn(`Admin consent failed (may need manual grant): ${err.message}`);
  }
}

async function createClientSecret(appId) {
  log.info("Generating client secret...");
  const raw = await azCommand([
    "ad", "app", "credential", "reset",
    "--id", appId,
    "--append",
    "-o", "json",
  ]);
  const cred = JSON.parse(raw);
  log.success("Client secret created");
  return {
    tenantId: cred.tenant,
    clientId: cred.appId,
    clientSecret: cred.password,
  };
}

async function logout() {
  log.info("Logging out...");
  try {
    await azCommand(["logout"]);
    log.success("Logged out");
  } catch {
    log.warn("Logout returned an error (may already be logged out)");
  }
}

module.exports = {
  login,
  validateLogin,
  createAppRegistration,
  addPermissions,
  grantAdminConsent,
  createClientSecret,
  logout,
};
