const { Builder, By, until } = require("selenium-webdriver");
const chrome = require("selenium-webdriver/chrome");
const log = require("./logger");
let otpLib;
try { otpLib = require("otpauth"); } catch { otpLib = null; }

const TIMEOUT = 60_000;

// Helper: wait for element to appear and be visible
async function waitAndFind(driver, locator, timeout = TIMEOUT) {
  const endTime = Date.now() + timeout;
  while (Date.now() < endTime) {
    try {
      const el = await driver.findElement(locator);
      if (await el.isDisplayed()) return el;
    } catch { /* retry */ }
    await driver.sleep(500);
  }
  throw new Error(`Element not found: ${locator}`);
}

// Helper: try to find element, return null if not found
async function tryFind(driver, locator, timeout = 3000) {
  try {
    return await waitAndFind(driver, locator, timeout);
  } catch {
    return null;
  }
}

// Helper: check for error banners
async function checkForError(driver) {
  for (const sel of ["#usernameError", "#passwordError", ".alert-error", "#errorText"]) {
    try {
      const el = await driver.findElement(By.css(sel));
      if (await el.isDisplayed()) return await el.getText();
    } catch { /* next */ }
  }
  return null;
}

async function browserLogin(email, password, newPassword, deviceCode, mfaSecret) {
  log.info("Launching Chrome browser for device code login...");

  const options = new chrome.Options();
  options.addArguments("--disable-blink-features=AutomationControlled");
  options.addArguments("--incognito");
  options.addArguments("--no-sandbox");
  options.addArguments("--disable-dev-shm-usage");
  options.excludeSwitches("enable-automation");

  const driver = await new Builder()
    .forBrowser("chrome")
    .setChromeOptions(options)
    .build();

  let passwordChanged = false;

  try {
    // Step 1: Device login page
    log.info("Opening device login page...");
    await driver.get("https://microsoft.com/devicelogin");

    // Step 2: Enter device code
    log.info(`Entering device code: ${deviceCode}`);
    const codeInput = await waitAndFind(driver, By.id("otc"));
    await driver.sleep(500);
    await codeInput.sendKeys(deviceCode);
    const nextBtn = await driver.findElement(By.id("idSIButton9"));
    await nextBtn.click();
    log.success("Device code submitted");

    // Step 3: Enter email
    log.info("Waiting for email field...");
    await driver.sleep(2000);
    const emailInput = await waitAndFind(driver, By.name("loginfmt"));
    await driver.sleep(500);
    await emailInput.clear();
    await emailInput.sendKeys(email);
    log.info(`Email entered: ${email}`);
    await driver.sleep(500);
    const emailNext = await waitAndFind(driver, By.id("idSIButton9"));
    await emailNext.click();
    log.info("Email next clicked");

    await driver.sleep(2000);
    let err = await checkForError(driver);
    if (err) throw new Error(`Email error: ${err}`);

    // Step 4: Enter password
    log.info("Waiting for password field...");
    await driver.sleep(2000);
    const passwordInput = await waitAndFind(driver, By.name("passwd"));
    await driver.sleep(500);
    await passwordInput.click();
    await passwordInput.clear();
    await passwordInput.sendKeys(password);
    log.info("Password entered");
    await driver.sleep(500);
    const signInBtn = await waitAndFind(driver, By.id("idSIButton9"));
    await signInBtn.click();
    log.info("Sign in clicked");

    await driver.sleep(3000);
    err = await checkForError(driver);
    if (err) throw new Error(`Login error: ${err}`);

    // Step 5: Check if "Update your password" page appeared
    const pageText = await driver.findElement(By.tagName("body")).getText();
    log.info(`Page after sign-in: ${pageText.substring(0, 100)}`);

    if (pageText.includes("Update your password") || pageText.includes("update your password")) {
      log.info("PASSWORD CHANGE page detected!");

      if (!newPassword) {
        throw new Error("Password change required but no new password in column C");
      }

      // Fill current password
      const currentPwd = await tryFind(driver, By.id("iPassword"), 5000);
      if (currentPwd) {
        await currentPwd.clear();
        await currentPwd.sendKeys(password);
        log.info("Current password filled");
      } else {
        log.info("No current password field found, trying alternate...");
        const altCurrent = await tryFind(driver, By.name("oldPassword"), 5000);
        if (altCurrent) {
          await altCurrent.clear();
          await altCurrent.sendKeys(password);
          log.info("Current password filled (alt)");
        }
      }

      await driver.sleep(500);

      // Fill new password
      const newPwd = await tryFind(driver, By.id("iNewPassword"), 5000);
      if (newPwd) {
        await newPwd.clear();
        await newPwd.sendKeys(newPassword);
        log.info("New password filled");
      } else {
        const altNew = await tryFind(driver, By.name("newPassword"), 5000);
        if (altNew) {
          await altNew.clear();
          await altNew.sendKeys(newPassword);
          log.info("New password filled (alt)");
        }
      }

      await driver.sleep(500);

      // Fill confirm password
      const confirmPwd = await tryFind(driver, By.id("iConfirmPassword"), 5000);
      if (confirmPwd) {
        await confirmPwd.clear();
        await confirmPwd.sendKeys(newPassword);
        log.info("Confirm password filled");
      } else {
        const altConfirm = await tryFind(driver, By.name("confirmNewPassword"), 5000);
        if (altConfirm) {
          await altConfirm.clear();
          await altConfirm.sendKeys(newPassword);
          log.info("Confirm password filled (alt)");
        }
      }

      await driver.sleep(500);

      // If none of the known IDs worked, try finding all password inputs
      const allInputs = await driver.findElements(By.css("input[type='password']"));
      log.info(`Found ${allInputs.length} password input(s) on page`);
      if (allInputs.length === 3) {
        // Current, New, Confirm
        await allInputs[0].clear(); await allInputs[0].sendKeys(password);
        await allInputs[1].clear(); await allInputs[1].sendKeys(newPassword);
        await allInputs[2].clear(); await allInputs[2].sendKeys(newPassword);
        log.info("Filled all 3 password fields by index");
      } else if (allInputs.length === 2) {
        // New, Confirm (current already filled or not needed)
        await allInputs[0].clear(); await allInputs[0].sendKeys(newPassword);
        await allInputs[1].clear(); await allInputs[1].sendKeys(newPassword);
        log.info("Filled 2 password fields (new + confirm)");
      }

      // Click submit
      await driver.sleep(500);
      const submitBtn = await waitAndFind(driver, By.id("idSIButton9"), 10_000);
      await submitBtn.click();
      log.info("Password change submitted");

      await driver.sleep(3000);
      err = await checkForError(driver);
      if (err) throw new Error(`Password change error: ${err}`);

      passwordChanged = true;
      log.success("Password changed successfully!");
    }

    // Step 5b: Handle MFA - if mfaSecret provided, generate OTP
    if (mfaSecret) {
      log.info("Checking for MFA/OTP prompt...");
      await driver.sleep(2000);
      const mfaPage = await driver.findElement(By.tagName("body")).getText();
      const mfaLower = mfaPage.toLowerCase();

      if (mfaLower.includes("authenticator") || mfaLower.includes("verification code") ||
          mfaLower.includes("enter code") || mfaLower.includes("security defaults") ||
          mfaLower.includes("action required")) {
        log.info("MFA page detected, generating OTP from saved secret...");

        // Click through intermediate pages (Action Required, etc.)
        for (let attempt = 0; attempt < 5; attempt++) {
          await driver.sleep(1500);
          const bodyText = (await driver.findElement(By.tagName("body")).getText()).toLowerCase();

          // Look for OTP input field
          let otpInput = await tryFind(driver, By.id("idTxtBx_SAOTCC_OTC"), 2000);
          if (!otpInput) otpInput = await tryFind(driver, By.name("otc"), 1000);
          if (!otpInput) {
            const inputs = await driver.findElements(By.css("input[type='tel'], input[type='text']"));
            for (const inp of inputs) {
              try {
                const ph = await inp.getAttribute("placeholder");
                const aria = await inp.getAttribute("aria-label");
                if ((ph && ph.toLowerCase().includes("code")) || (aria && aria.toLowerCase().includes("code"))) {
                  otpInput = inp;
                  break;
                }
              } catch {}
            }
          }

          if (otpInput) {
            // Generate OTP
            let otp;
            try {
              // Clean the secret: remove spaces, uppercase
              const cleanSecret = mfaSecret.replace(/\s+/g, "").toUpperCase();
              // Pad to multiple of 8 for base32
              const padded = cleanSecret + "=".repeat((8 - (cleanSecret.length % 8)) % 8);
              if (otpLib) {
                const totp = new otpLib.TOTP({ secret: otpLib.Secret.fromBase32(padded) });
                otp = totp.generate();
              } else {
                const { execSync } = require("child_process");
                otp = execSync(`python3 -c "import pyotp; print(pyotp.TOTP('${padded}').now())"`).toString().trim();
              }
            } catch (otpErr) {
              log.error(`OTP generation failed: ${otpErr.message}`);
              throw new Error(`Cannot generate OTP from secret key: ${otpErr.message}`);
            }
            log.info(`OTP generated: ${otp}`);
            await otpInput.clear();
            await otpInput.sendKeys(otp);
            await driver.sleep(500);

            // Click verify
            let verifyBtn = await tryFind(driver, By.id("idSubmit_SAOTCC_Continue"), 3000);
            if (!verifyBtn) verifyBtn = await tryFind(driver, By.id("idSIButton9"), 2000);
            if (verifyBtn) await verifyBtn.click();
            log.success("OTP entered and verified");
            await driver.sleep(3000);
            break;
          }

          // Click Next on intermediate pages
          const nextBtn = await tryFind(driver, By.id("idSubmit_ProofUp_Redirect"), 1500);
          if (nextBtn) { await nextBtn.click(); log.info("Clicked Next on MFA page"); continue; }
          const nextBtn2 = await tryFind(driver, By.id("idSIButton9"), 1500);
          if (nextBtn2) { await nextBtn2.click(); log.info("Clicked Next"); continue; }
        }
      }
    }

    // Step 6: Handle "Stay signed in?"
    log.info("Checking for 'Stay signed in' prompt...");
    try {
      await waitAndFind(driver, By.id("KmsiDescription"), 10_000);
      log.info("'Stay signed in?' detected");
      const yesBtn = await driver.findElement(By.id("idSIButton9"));
      await yesBtn.click();
      log.info("Clicked 'Yes'");
    } catch {
      log.info("No 'Stay signed in' prompt");
    }

    // Step 7: Confirmation page ("Are you trying to sign in to Azure CLI?")
    log.info("Waiting for confirmation...");
    await driver.sleep(3000);
    try {
      const confirmBtn = await waitAndFind(driver, By.id("idSIButton9"), 15_000);
      const btnText = await confirmBtn.getText();
      log.info(`Confirmation: "${btnText}" — clicking...`);
      await confirmBtn.click();
    } catch {
      log.info("No confirmation button");
    }

    // Step 8: Check for success
    await driver.sleep(3000);
    const finalText = await driver.findElement(By.tagName("body")).getText();
    if (finalText.includes("You have signed in") || finalText.includes("successfully")) {
      log.success("Login confirmed in browser!");
    } else {
      log.info(`Final page: ${finalText.substring(0, 200)}`);
    }

    log.success("Browser login flow completed");
    return { passwordChanged };
  } finally {
    await driver.quit();
    log.info("Chrome closed");
  }
}

module.exports = { browserLogin };
