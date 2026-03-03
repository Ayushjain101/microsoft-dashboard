#!/usr/bin/env node
/**
 * test-mfa.js - Manually check MFA state for a tenant
 * Usage: node test-mfa.js <tenantId> <clientId> <clientSecret>
 */

async function main() {
  const [tenantId, clientId, clientSecret] = process.argv.slice(2);
  if (!tenantId || !clientId || !clientSecret) {
    console.log("Usage: node test-mfa.js <tenantId> <clientId> <clientSecret>");
    process.exit(1);
  }

  // 1. Get token
  console.log("Getting token...");
  const tokenRes = await fetch(`https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: clientId,
      client_secret: clientSecret,
      scope: "https://graph.microsoft.com/.default",
    }).toString(),
  });
  const tokenData = await tokenRes.json();
  if (!tokenRes.ok) {
    console.error("Token error:", tokenData);
    process.exit(1);
  }
  const token = tokenData.access_token;
  console.log("Token OK\n");

  const headers = { Authorization: `Bearer ${token}` };
  const get = async (url) => {
    const res = await fetch(url, { headers });
    return res.json();
  };

  // 2. Check Security Defaults
  console.log("=== Security Defaults ===");
  const sd = await get("https://graph.microsoft.com/v1.0/policies/identitySecurityDefaultsEnforcementPolicy");
  console.log("  isEnabled:", sd.isEnabled);

  // 3. Check Conditional Access policies
  console.log("\n=== Conditional Access Policies ===");
  try {
    const ca = await get("https://graph.microsoft.com/v1.0/identity/conditionalAccess/policies");
    if (ca.value && ca.value.length > 0) {
      for (const p of ca.value) {
        const mfaRequired = (p.grantControls?.builtInControls || []).includes("mfa");
        console.log(`  "${p.displayName}" - state: ${p.state} - MFA: ${mfaRequired}`);
      }
    } else {
      console.log("  None");
    }
  } catch (e) {
    console.log("  Error:", e.message.substring(0, 80));
  }

  // 4. Check users
  console.log("\n=== Users ===");
  const usersData = await get("https://graph.microsoft.com/v1.0/users?$select=id,userPrincipalName");
  const users = usersData.value || [];

  for (const user of users) {
    console.log(`\n--- ${user.userPrincipalName} ---`);

    // Per-user MFA
    try {
      const mfa = await get(`https://graph.microsoft.com/beta/users/${user.id}/authentication/requirements`);
      console.log("  Per-user MFA:", mfa.perUserMfaState);
    } catch (e) {
      console.log("  Per-user MFA: error -", e.message.substring(0, 60));
    }

    // ALL auth methods
    try {
      const methods = await get(`https://graph.microsoft.com/v1.0/users/${user.id}/authentication/methods`);
      console.log("  Auth methods:");
      for (const m of (methods.value || [])) {
        const type = m["@odata.type"].replace("#microsoft.graph.", "");
        console.log(`    - ${type} (id: ${m.id})`);
      }
      if (!methods.value || methods.value.length === 0) {
        console.log("    None");
      }
    } catch (e) {
      console.log("  Auth methods: error -", e.message.substring(0, 60));
    }

    // Authenticator apps
    try {
      const auth = await get(`https://graph.microsoft.com/v1.0/users/${user.id}/authentication/microsoftAuthenticatorMethods`);
      console.log("  Authenticator apps:", (auth.value || []).length);
      for (const a of (auth.value || [])) {
        console.log(`    - ${a.displayName || "unnamed"} (id: ${a.id}, device: ${a.deviceTag || "?"})`);
      }
    } catch (e) {}

    // Software OATH
    try {
      const oath = await get(`https://graph.microsoft.com/v1.0/users/${user.id}/authentication/softwareOathMethods`);
      console.log("  Software OATH tokens:", (oath.value || []).length);
    } catch (e) {}
  }

  console.log("\n=== Authentication Methods Policy ===");
  try {
    const amp = await get("https://graph.microsoft.com/v1.0/policies/authenticationMethodsPolicy");
    console.log("  Registration campaign:", amp.registrationCampaign?.state);
    const configs = amp.authenticationMethodConfigurations || [];
    for (const c of configs) {
      console.log(`  ${c.id}: state=${c.state}`);
    }
  } catch (e) {
    console.log("  Error:", e.message.substring(0, 80));
  }

  console.log("\nDone.");
}

main().catch(console.error);
