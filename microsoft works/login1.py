#!/usr/bin/env python3
"""
login1.py - Microsoft Login + MFA Auto-Setup with OTP Generation
=================================================================
Full browser automation flow:
  1. Open Chrome -> device code page
  2. Enter email -> Next
  3. Enter password -> Sign in
  4. Handle password change (current -> new -> confirm -> Next)   
  5. MFA setup: Click "I can't scan the QR code" to get secret key
  6. Copy secret key -> generate OTP with pyotp
  7. Enter OTP -> Next/Verify
  8. Complete login -> setup app registration

Reads credentials from Google Sheet (columns B=email, C=password, D=new password)

Usage:
  python login1.py --email admin@domain.com --password "Pass123!"
  python login1.py --email admin@domain.com --password "Old" --new-password "New123!"
  python login1.py --sheet <SHEET_ID>
  python login1.py --skip-login
"""

import os
import sys
import json
import time
import argparse
import subprocess
import threading
import re
import base64
from datetime import datetime


# --- Auto-install dependencies ---
def ensure_packages():
    required = {
        "selenium": "selenium",
        "requests": "requests",
        "pyotp": "pyotp",
    }
    for pkg, pip_name in required.items():
        try:
            __import__(pkg)
        except ImportError:
            print(f"Installing {pip_name}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name, "-q"])

ensure_packages()

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import requests
import pyotp


# --- Logging ---
def log(level, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {level:5s}  {msg}")

def info(msg):  log("INFO", msg)
def ok(msg):    log(" OK ", msg)
def warn(msg):  log("WARN", msg)
def err(msg):   log("ERROR", msg)


# --- Google Sheets via Apps Script ---
def read_from_google_sheet(sheet_id, apps_script_url=None):
    """Read credentials from Google Sheet via Apps Script web app.
    Columns: B=email, C=password, D=new password.
    """
    info("Reading credentials from Google Sheet via Apps Script...")

    # Find Apps Script URL from args, .env, or hardcoded
    if not apps_script_url:
        apps_script_url = os.environ.get("APPS_SCRIPT_URL", "")

    if not apps_script_url:
        err("No Apps Script URL found!")
        err("Set APPS_SCRIPT_URL in .env or pass --apps-script-url")
        err("")
        err("To create one:")
        err("  1. Open your Google Sheet")
        err("  2. Extensions > Apps Script")
        err("  3. Paste the doGet function code")
        err("  4. Deploy > New deployment > Web app > Anyone > Deploy")
        err("  5. Copy the URL and add to .env: APPS_SCRIPT_URL=https://script.google.com/...")
        return []

    try:
        # Call Apps Script with sheet ID
        url = f"{apps_script_url}?id={sheet_id}"
        info(f"  Fetching: {url[:80]}...")
        resp = requests.get(url, timeout=30)

        if resp.status_code != 200:
            err(f"Apps Script returned {resp.status_code}: {resp.text[:200]}")
            return []

        text = resp.text.strip()
        if not text or text.startswith("<!"):
            err("Apps Script returned empty or HTML response")
            return []

        try:
            data = resp.json()
        except Exception:
            err(f"Apps Script returned invalid JSON: {text[:100]}")
            return []

        # Handle both formats: direct list or {value: [...]}
        if isinstance(data, dict) and "value" in data:
            data = data["value"]
        if isinstance(data, dict):
            data = [data]

        if not data:
            warn("No credentials found in sheet")
            return []

        ok(f"  Found {len(data)} credential(s) in sheet")
        for i, row in enumerate(data):
            info(f"    [{i+1}] {row.get('email', '?')}")

        return data

    except Exception as e:
        err(f"Sheet read error: {e}")
        return []


def write_to_google_sheet(apps_script_url, action, row, **kwargs):
    """Write data back to Google Sheet via Apps Script POST.

    Actions:
      credentials - write tenant_id, client_id, client_secret, secret_key, status
      status      - update status column only
      error       - write FAILED status with message
      updatePassword - update password in column C
    """
    if not apps_script_url:
        apps_script_url = os.environ.get("APPS_SCRIPT_URL", "")
    if not apps_script_url:
        warn("No Apps Script URL - skipping sheet update")
        return False

    payload = {"action": action, "row": row}
    payload.update(kwargs)

    try:
        resp = requests.post(
            apps_script_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        # Google Apps Script may return empty body, HTML, or valid JSON
        text = resp.text.strip()
        if not text or text.startswith("<!"):
            # Empty or HTML response — POST was still processed by Apps Script
            ok(f"  Sheet updated (row {row}, action={action})")
            return True

        try:
            result = resp.json()
        except Exception:
            ok(f"  Sheet updated (row {row}, action={action})")
            return True

        if result.get("result") == "ok":
            ok(f"  Sheet updated (row {row}, action={action})")
            return True
        else:
            warn(f"  Sheet update response: {result}")
            return False
    except Exception as e:
        warn(f"  Sheet update failed: {e}")
        return False


# --- Selenium Helpers ---
def wait_for(driver, by, value, timeout=30):
    """Wait for element to be visible and return it."""
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, value))
    )

def try_find(driver, by, value, timeout=5):
    """Try to find element, return None if not found."""
    try:
        return WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )
    except Exception:
        return None

def try_click(driver, by, value, timeout=5):
    """Try to find and click element, return True if clicked."""
    el = try_find(driver, by, value, timeout)
    if el:
        try:
            el.click()
            return True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", el)
                return True
            except Exception:
                pass
    return False

def safe_type(element, text):
    """Clear field and type text safely."""
    element.click()
    time.sleep(0.2)
    element.clear()
    time.sleep(0.1)
    element.send_keys(text)

def check_error(driver):
    """Check for error messages on page."""
    for sel in ["#usernameError", "#passwordError", ".alert-error", "#errorText",
                "[role='alert']", ".error-text"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed() and el.text.strip():
                return el.text.strip()
        except Exception:
            pass
    return None

def get_page_text(driver):
    """Get visible page text (lowercase), stripping non-printable/icon characters."""
    try:
        text = driver.find_element(By.TAG_NAME, "body").text.lower()
        # Remove non-ASCII icon characters (Microsoft uses private-use Unicode like \ue72b)
        return text.encode("ascii", "ignore").decode("ascii")
    except Exception:
        return ""

def click_next_button(driver, timeout=10):
    """Click the Next/Submit/Verify button."""
    # Try common Microsoft button IDs (order matters!)
    for btn_id in [
        "idSubmit_ProofUp_Redirect",   # MFA setup Next button (appears 3 times)
        "idSIButton9",                  # General Next/Sign in button
        "idSubmit_SAOTCC_Continue",     # OTP verify button
        "idBtn_Back",                   # Back/Continue button
    ]:
        if try_click(driver, By.ID, btn_id, timeout=3):
            return True
    # Try by value attribute (input buttons)
    for text in ["Next", "Verify", "Yes", "Continue", "Submit", "Sign in"]:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, f"input[value='{text}'], button")
            for btn in btns:
                if btn.is_displayed():
                    btn_text = btn.text or btn.get_attribute("value") or ""
                    if text.lower() in btn_text.lower():
                        btn.click()
                        return True
        except Exception:
            pass
    return False


# --- OTP Generation ---
def extract_secret_from_page(driver):
    """Extract TOTP secret key from the MFA setup page text."""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        # Microsoft shows secret key in various formats
        patterns = [
            r"(?:Secret\s*(?:key)?|Key|Code)[:\s]+([A-Z2-7]{16,})",
            r"(?:secret|key)[=:\s]+([a-zA-Z2-7]{16,})",
            r"\b([A-Z2-7]{32,64})\b",  # standalone base32 string
            r"\b([A-Z2-7]{16,31})\b",  # shorter base32 string
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                secret = match.group(1).strip().upper()
                # Validate it looks like base32
                if len(secret) >= 16 and re.match(r'^[A-Z2-7]+$', secret):
                    ok(f"Found secret key: {secret[:8]}...{secret[-4:]}")
                    return secret
    except Exception as e:
        info(f"Could not extract secret from text: {e}")
    return None


def extract_secret_from_qr(driver):
    """Try to extract secret from QR code image on page."""
    try:
        from pyzbar.pyzbar import decode as decode_qr
        from PIL import Image
        import io

        imgs = driver.find_elements(By.TAG_NAME, "img")
        for img in imgs:
            src = img.get_attribute("src") or ""
            alt = (img.get_attribute("alt") or "").lower()
            # Look for QR code image
            if any(kw in src.lower() + alt for kw in ["qr", "barcode", "authenticator", "totp"]):
                if src.startswith("data:image"):
                    img_data = base64.b64decode(src.split(",")[1])
                    pil_img = Image.open(io.BytesIO(img_data))
                    results = decode_qr(pil_img)
                    if results:
                        qr_text = results[0].data.decode()
                        match = re.search(r"secret=([A-Z2-7]+)", qr_text, re.IGNORECASE)
                        if match:
                            secret = match.group(1).upper()
                            ok(f"QR decoded: {secret[:8]}...")
                            return secret
    except ImportError:
        info("pyzbar not available, skipping QR decode")
    except Exception as e:
        info(f"QR decode failed: {e}")
    return None


def click_cant_scan_link(driver):
    """Click 'I can't scan the QR code' or similar link to show secret key text."""
    # Microsoft MFA setup page has links like:
    # "Can't scan image?", "I can't scan the barcode", "Enter code manually"
    link_texts = [
        "can't scan",
        "cant scan",
        "can not scan",
        "enter code manually",
        "manual entry",
        "enter manually",
        "configure without",
        "without scanning",
        "text code",
        "different method",
        "can't use",
        "i want to set up a different method",
    ]

    # Try by link text / partial link text
    for text in link_texts:
        try:
            links = driver.find_elements(By.PARTIAL_LINK_TEXT, text)
            for link in links:
                if link.is_displayed():
                    info(f"  Clicking: '{link.text}'")
                    link.click()
                    time.sleep(2)
                    return True
        except Exception:
            pass

    # Try by all <a> tags text content
    try:
        all_links = driver.find_elements(By.TAG_NAME, "a")
        for link in all_links:
            link_text = link.text.lower()
            if any(kw in link_text for kw in link_texts):
                if link.is_displayed():
                    info(f"  Clicking link: '{link.text}'")
                    link.click()
                    time.sleep(2)
                    return True
    except Exception:
        pass

    # Try by buttons with similar text
    try:
        all_btns = driver.find_elements(By.TAG_NAME, "button")
        for btn in all_btns:
            btn_text = btn.text.lower()
            if any(kw in btn_text for kw in link_texts):
                if btn.is_displayed():
                    info(f"  Clicking button: '{btn.text}'")
                    btn.click()
                    time.sleep(2)
                    return True
    except Exception:
        pass

    # Try by spans/divs that look clickable
    try:
        clickables = driver.find_elements(By.CSS_SELECTOR, "[role='link'], [role='button'], .link, .clickable")
        for el in clickables:
            el_text = el.text.lower()
            if any(kw in el_text for kw in link_texts):
                if el.is_displayed():
                    info(f"  Clicking: '{el.text}'")
                    el.click()
                    time.sleep(2)
                    return True
    except Exception:
        pass

    return False


def generate_otp(secret_key):
    """Generate 6-digit TOTP code from secret key."""
    try:
        secret = secret_key.replace(" ", "").upper()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        # Check remaining time - if less than 5 seconds, wait for next code
        remaining = totp.interval - (int(time.time()) % totp.interval)
        if remaining < 5:
            info(f"  OTP expires in {remaining}s, waiting for new code...")
            time.sleep(remaining + 1)
            code = totp.now()
        ok(f"  OTP generated: {code} (valid for {remaining}s)")
        return code
    except Exception as e:
        err(f"OTP generation failed: {e}")
        return None


def find_otp_input(driver):
    """Find the OTP/verification code input field."""
    # Try various selectors Microsoft uses for OTP input
    selectors = [
        "input#idTxtBx_SAOTCC_OTC",             # Microsoft OTP field
        "input[name='otc']",                      # OTP code field
        "input[aria-label*='code']",              # aria label with 'code'
        "input[aria-label*='Code']",
        "input[placeholder*='code']",             # placeholder with 'code'
        "input[placeholder*='Code']",
        "input[type='tel']",                      # numeric input
        "input[type='number']",                   # number input
        "input[aria-label*='verification']",
        "input[aria-label*='Verification']",
        "input[id*='otp']",
        "input[id*='OTP']",
        "input[id*='code']",
        "input[id*='Code']",
        "input[name*='otp']",
        "input[name*='code']",
    ]
    for sel in selectors:
        el = try_find(driver, By.CSS_SELECTOR, sel, timeout=2)
        if el:
            return el

    # Fallback: find visible text inputs that might be OTP
    try:
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='tel'], input[type='number'], input:not([type])")
        for inp in inputs:
            if inp.is_displayed() and inp.is_enabled():
                # Check if it looks like an OTP field (short max length, numeric pattern)
                maxlen = inp.get_attribute("maxlength") or ""
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                aria = (inp.get_attribute("aria-label") or "").lower()
                if maxlen in ["6", "8"] or "code" in placeholder or "code" in aria:
                    return inp
    except Exception:
        pass

    return None


# --- Main Browser Login Flow ---
def wait_page_load(driver, seconds=3):
    """Wait for page to settle after navigation."""
    time.sleep(seconds)
    # Wait for body to be present
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except Exception:
        pass


def is_login_done(driver):
    """Check if we've passed all login/MFA pages."""
    page_text = get_page_text(driver)
    url = driver.current_url
    if any(kw in page_text for kw in [
        "you have signed in", "you're all set",
        "are you trying to sign in", "stay signed in"
    ]):
        return True
    if "kmsi" in url or "appconfirm" in url:
        return True
    return False


def browser_login(email, password, new_password, device_code=None, mfa_secret=None):
    """
    Opens incognito Chrome and handles full login:
    - If device_code: enters code at devicelogin first, then full login flow
    - If no device_code: goes to admin.microsoft.com, then full login flow
    - If mfa_secret: uses saved secret key to generate OTP (skips MFA setup)
    Both modes handle: email, password, password change, MFA setup
    """
    info("Launching Chrome...")

    options = ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--incognito")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Try main display first, fallback to headless
    display = os.environ.get("DISPLAY", "")
    if not display:
        # Check if :1001 is available
        try:
            test_result = subprocess.run(["xdpyinfo", "-display", ":1001"],
                capture_output=True, timeout=3)
            if test_result.returncode == 0:
                os.environ["DISPLAY"] = ":1001"
                options.add_argument("--start-maximized")
                info("  Using display :1001")
            else:
                options.add_argument("--headless=new")
                info("  Using headless mode")
        except Exception:
            options.add_argument("--headless=new")
            info("  Using headless mode")
    else:
        options.add_argument("--start-maximized")
        info(f"  Using display {display}")

    driver = webdriver.Chrome(options=options)
    password_changed = False
    saved_secret_key = mfa_secret if mfa_secret else None

    try:
        # ===== STEP 0: Device code entry (if device_code provided) =====
        if device_code:
            info("[Step 0] Entering device code...")
            driver.get("https://microsoft.com/devicelogin")
            time.sleep(3)

            code_input = wait_for(driver, By.ID, "otc", timeout=15)
            time.sleep(0.5)
            safe_type(code_input, device_code)
            info(f"  Code: {device_code}")
            time.sleep(0.5)
            click_next_button(driver)
            ok("  Device code submitted")
            wait_page_load(driver, 3)

            # Handle "are you trying to sign in" confirmation
            for _ in range(3):
                wait_page_load(driver, 2)
                page_text = get_page_text(driver)
                if "are you trying to sign in" in page_text:
                    try_click(driver, By.ID, "idSIButton9", timeout=3)
                    info("  Clicked Continue")
                    wait_page_load(driver, 2)
                    break
                time.sleep(1)

            # Now fall through to the FULL login flow below
            # (email, password, password change, MFA - all in same browser)

        # ===== STEP 1: Go to login page ==========
        if not device_code:
            info(f"[Step 1] Opening login page...")
            driver.get("https://admin.microsoft.com")
            time.sleep(3)

        # ========== STEP 2: Email ==========
        info("[Step 2] Email...")
        wait_page_load(driver, 3)
        email_input = wait_for(driver, By.NAME, "loginfmt")
        time.sleep(0.5)
        safe_type(email_input, email)
        info(f"  {email}")
        time.sleep(0.5)
        click_next_button(driver)
        wait_page_load(driver, 3)

        error = check_error(driver)
        if error:
            raise RuntimeError(f"Email error: {error}")
        ok("  Email accepted")

        # ========== STEP 3: Password ==========
        info("[Step 3] Password...")
        pwd_input = wait_for(driver, By.NAME, "passwd")
        time.sleep(0.5)
        safe_type(pwd_input, password)
        info("  Password entered")
        time.sleep(0.5)
        click_next_button(driver)  # Sign in click
        wait_page_load(driver, 4)

        error = check_error(driver)
        if error and new_password:
            # Password might already have been changed previously, try new password
            warn(f"  Password error: {error}")
            info("  Retrying with new password...")
            pwd_input = wait_for(driver, By.NAME, "passwd", timeout=10)
            time.sleep(0.5)
            safe_type(pwd_input, new_password)
            info("  New password entered")
            time.sleep(0.5)
            click_next_button(driver)
            wait_page_load(driver, 4)

            error2 = check_error(driver)
            if error2:
                raise RuntimeError(f"Password error (both passwords failed): {error2}")
            ok("  Signed in with new password")
            # Since new password already works, swap them so we don't try to change again
            password = new_password
            new_password = None
        elif error:
            raise RuntimeError(f"Password error: {error}")
        else:
            ok("  Signed in")

        # ========== STEP 4: Password Change ==========
        page_text = get_page_text(driver)

        if "update your password" in page_text or "change your password" in page_text or "change password" in page_text:
            info("[Step 4] Password change required!")
            if not new_password:
                raise RuntimeError("Password change forced but no --new-password provided!")

            time.sleep(1)

            # Fill current password
            current_pwd = try_find(driver, By.ID, "iPassword", 5)
            if current_pwd:
                safe_type(current_pwd, password)
            else:
                current_pwd = try_find(driver, By.NAME, "oldPassword", 5)
                if current_pwd:
                    safe_type(current_pwd, password)

            time.sleep(0.3)

            # Fill new password
            new_pwd_el = try_find(driver, By.ID, "iNewPassword", 5)
            if new_pwd_el:
                safe_type(new_pwd_el, new_password)
            else:
                new_pwd_el = try_find(driver, By.NAME, "newPassword", 5)
                if new_pwd_el:
                    safe_type(new_pwd_el, new_password)

            time.sleep(0.3)

            # Fill confirm password
            confirm_pwd = try_find(driver, By.ID, "iConfirmPassword", 5)
            if confirm_pwd:
                safe_type(confirm_pwd, new_password)
            else:
                confirm_pwd = try_find(driver, By.NAME, "confirmNewPassword", 5)
                if confirm_pwd:
                    safe_type(confirm_pwd, new_password)

            # Fallback: fill by password input index
            pwd_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            if len(pwd_inputs) == 3:
                safe_type(pwd_inputs[0], password)
                safe_type(pwd_inputs[1], new_password)
                safe_type(pwd_inputs[2], new_password)
            elif len(pwd_inputs) == 2:
                safe_type(pwd_inputs[0], new_password)
                safe_type(pwd_inputs[1], new_password)

            time.sleep(0.5)
            click_next_button(driver)  # Sign in with new password
            info("  Password change submitted")
            wait_page_load(driver, 4)

            error = check_error(driver)
            if error:
                raise RuntimeError(f"Password change error: {error}")

            password_changed = True
            ok("  Password changed!")

            # After password change, Microsoft may show up to 3 "Next" button pages
            # (e.g. "password updated", "keep your account secure", info pages)
            # Click through all of them before MFA setup
            for click_round in range(1, 4):
                wait_page_load(driver, 3)
                page_text = get_page_text(driver)

                # Stop if we've already reached MFA setup or login is done
                if is_login_done(driver):
                    info(f"  Post-password click {click_round}: login done, stopping")
                    break
                mfa_kw = ["authenticator", "more information required", "verify your identity",
                          "keep your account secure", "set up your account", "microsoft authenticator",
                          "security defaults", "action required", "multifactor authentication"]
                if any(kw in page_text for kw in mfa_kw):
                    info(f"  Post-password click {click_round}: MFA page reached, moving on")
                    break

                # Try clicking Next/Continue button
                clicked = False
                for btn_id in ["idSIButton9", "idSubmit_ProofUp_Redirect"]:
                    if try_click(driver, By.ID, btn_id, timeout=3):
                        info(f"  Post-password click {click_round}: clicked {btn_id}")
                        clicked = True
                        break
                if not clicked:
                    clicked = click_next_button(driver)
                    if clicked:
                        info(f"  Post-password click {click_round}: clicked Next")
                if not clicked:
                    info(f"  Post-password click {click_round}: no button found, moving on")
                    break
        else:
            info("[Step 4] No password change - skipping")

        # ========== STEP 5: MFA Setup ==========
        # Flow: password change page -> Next -> Next -> Next -> QR page ->
        #       click "Can't scan" -> secret key page -> copy key ->
        #       click Next -> OTP page -> enter OTP -> verify
        wait_page_load(driver, 3)
        page_text = get_page_text(driver)

        mfa_keywords = [
            "more information required", "verify your identity",
            "authenticator", "keep your account secure",
            "additional security verification", "multi-factor",
            "microsoft authenticator", "set up your account",
            "security defaults", "action required", "multifactor authentication",
            "install microsoft authenticator", "set up a different",
            "authentication app", "authenticator app",
        ]

        if any(kw in page_text for kw in mfa_keywords) and mfa_secret:
            # ===== MFA with SAVED secret key (just generate OTP) =====
            info("[Step 5] MFA detected - using saved secret key to generate OTP")
            saved_secret_key = mfa_secret

            # Click through any "Action Required" / intermediate pages
            for _ in range(5):
                wait_page_load(driver, 2)
                page_text = get_page_text(driver)

                # Look for OTP input field
                otp_field = find_otp_input(driver)
                if otp_field:
                    otp_code = generate_otp(saved_secret_key)
                    safe_type(otp_field, otp_code)
                    time.sleep(0.5)
                    verify_btn = try_find(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3)
                    if verify_btn:
                        try:
                            verify_btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", verify_btn)
                    else:
                        click_next_button(driver)
                    ok(f"  OTP entered using saved secret key")
                    wait_page_load(driver, 3)
                    break

                # Click Next / Yes on intermediate pages
                if try_click(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=2):
                    info("  Clicked Next on Action Required")
                    wait_page_load(driver, 2)
                    continue
                if try_click(driver, By.ID, "idSIButton9", timeout=2):
                    info("  Clicked Next/Yes")
                    wait_page_load(driver, 2)
                    continue
                time.sleep(2)

            # Click Done if present
            for btn_text in ["Done", "done", "Finish", "finish"]:
                if try_click(driver, By.XPATH, f"//button[contains(text(),'{btn_text}')]", timeout=2):
                    ok("  Clicked Done")
                    wait_page_load(driver, 2)
                    break

        elif any(kw in page_text for kw in mfa_keywords):
            # ===== MFA FIRST TIME SETUP (no saved secret) =====
            info("[Step 5] MFA SETUP DETECTED!")
            info("=" * 50)

            # --- 5a: "Action Required / Security defaults" page -> click Next ---
            info("  5a: Clicking Next on Action Required page...")
            proofup_btn = try_find(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=8)
            if proofup_btn:
                try:
                    proofup_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", proofup_btn)
                ok("  Next clicked on Action Required page")
            else:
                click_next_button(driver)
            wait_page_load(driver, 4)

            # --- 5b: "Install Microsoft Authenticator" page -> click "Set up a different authentication app" ---
            info("  5b: Looking for 'Set up a different authentication app'...")
            diff_app_clicked = False
            for attempt in range(5):
                # Try by partial link text
                for link_kw in ["different authentication app", "different authenticator app", "I want to use a different"]:
                    try:
                        links = driver.find_elements(By.PARTIAL_LINK_TEXT, link_kw)
                        for link in links:
                            if link.is_displayed():
                                driver.execute_script("arguments[0].click();", link)
                                diff_app_clicked = True
                                info(f"  Found via PARTIAL_LINK_TEXT: '{link_kw}'")
                                break
                    except Exception:
                        pass
                    if diff_app_clicked:
                        break
                # Try all <a> tags
                if not diff_app_clicked:
                    try:
                        for el in driver.find_elements(By.CSS_SELECTOR, "a"):
                            el_text = (el.text or "").lower()
                            if len(el_text) < 100 and "different" in el_text:
                                if el.is_displayed():
                                    driver.execute_script("arguments[0].click();", el)
                                    diff_app_clicked = True
                                    info(f"  Found via <a> tag: '{el_text[:50]}'")
                                    break
                    except Exception:
                        pass
                # Try buttons, spans, divs with role
                if not diff_app_clicked:
                    try:
                        for el in driver.find_elements(By.CSS_SELECTOR, "button, [role='button'], [role='link']"):
                            el_text = (el.text or "").lower()
                            if len(el_text) < 100 and "different" in el_text:
                                if el.is_displayed():
                                    driver.execute_script("arguments[0].click();", el)
                                    diff_app_clicked = True
                                    info(f"  Found via button/role: '{el_text[:50]}'")
                                    break
                    except Exception:
                        pass
                if diff_app_clicked:
                    break
                info(f"  Attempt {attempt+1}: not found yet, waiting...")
                time.sleep(3)

            if diff_app_clicked:
                ok("  Clicked 'Set up a different authentication app'")
            else:
                warn("  Could not find link, trying Next as fallback")
                click_next_button(driver)
            wait_page_load(driver, 4)

            # --- 5c: Click Next on the intermediate page (after "Set up a different") ---
            info("  5c: Clicking Next to proceed to QR code page...")
            proofup_btn = try_find(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=5)
            if proofup_btn:
                try:
                    proofup_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", proofup_btn)
                ok("  Next clicked")
            else:
                click_next_button(driver)
            wait_page_load(driver, 4)

            # --- 5d: "Scan the QR code" page -> click "Can't scan the QR code?" ---
            info("  5d: Looking for 'Can't scan the QR code?' on QR page...")
            cant_scan_clicked = False
            for attempt in range(5):
                # Try the specific data-testid button
                cant_scan_btn = try_find(driver, By.CSS_SELECTOR,
                    'button[data-testid="activation-qr-show/hide-info-button"]', timeout=3)
                if cant_scan_btn:
                    try:
                        cant_scan_btn.click()
                        cant_scan_clicked = True
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", cant_scan_btn)
                            cant_scan_clicked = True
                        except Exception:
                            pass
                if not cant_scan_clicked:
                    # Try generic "can't scan" links/buttons
                    cant_scan_clicked = click_cant_scan_link(driver)
                if cant_scan_clicked:
                    break
                info(f"  Attempt {attempt+1}: 'Can't scan' not found yet...")
                time.sleep(2)

            if cant_scan_clicked:
                ok("  Clicked 'Can't scan the QR code?'")
            else:
                warn("  Could not find 'Can't scan' button")
            wait_page_load(driver, 3)

            # --- 5e: Copy the secret key ---
            info("  5e: Extracting secret key...")
            saved_secret_key = extract_secret_from_page(driver)
            if not saved_secret_key:
                info("  Searching page elements for secret key...")
                try:
                    for el in driver.find_elements(By.CSS_SELECTOR,
                            "div, span, p, code, pre, input[type='text'], td, label"):
                        txt = el.text.strip()
                        if txt and len(txt) >= 16 and re.match(r'^[A-Z2-7]+$', txt):
                            saved_secret_key = txt
                            break
                        val = el.get_attribute("value") or ""
                        if val and len(val) >= 16 and re.match(r'^[A-Z2-7]+$', val.upper()):
                            saved_secret_key = val.upper()
                            break
                except Exception:
                    pass

            if saved_secret_key:
                ok(f"  SECRET KEY: {saved_secret_key[:8]}...{saved_secret_key[-4:]}")
            else:
                warn("  Could not find secret key!")

            # --- 5f: Generate OTP, click Next on secret key page ---
            if saved_secret_key:
                otp_code = generate_otp(saved_secret_key)
                ok(f"  OTP generated: {otp_code}")

                info("  5f: Clicking Next on secret key page...")
                click_next_button(driver)
                wait_page_load(driver, 4)

                # --- 5g: Fill OTP and click verify/done ---
                info("  5g: Looking for OTP input field...")
                otp_field = find_otp_input(driver)
                if not otp_field:
                    for wait_try in range(10):
                        time.sleep(2)
                        otp_field = find_otp_input(driver)
                        if otp_field:
                            break
                        # Try clicking Next if a button appears
                        if try_find(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=1):
                            try_click(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=2)
                            wait_page_load(driver, 3)
                        elif try_find(driver, By.ID, "idSIButton9", timeout=1):
                            try_click(driver, By.ID, "idSIButton9", timeout=2)
                            wait_page_load(driver, 3)

                if otp_field:
                    # Regenerate fresh OTP in case time passed
                    otp_code = generate_otp(saved_secret_key)
                    safe_type(otp_field, otp_code)
                    info(f"  OTP entered: {otp_code}")
                    time.sleep(0.5)

                    # Click Verify/Next/Done
                    verify_btn = try_find(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3)
                    if verify_btn:
                        try:
                            verify_btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", verify_btn)
                    else:
                        click_next_button(driver)
                    ok("  OTP submitted!")
                    wait_page_load(driver, 4)

                    # Retry if OTP was rejected (expired)
                    error = check_error(driver)
                    if error:
                        warn(f"  OTP error: {error}, retrying...")
                        otp_code = generate_otp(saved_secret_key)
                        otp_field = find_otp_input(driver)
                        if otp_field and otp_code:
                            safe_type(otp_field, otp_code)
                            time.sleep(0.5)
                            verify_btn = try_find(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3)
                            if verify_btn:
                                try:
                                    verify_btn.click()
                                except Exception:
                                    driver.execute_script("arguments[0].click();", verify_btn)
                            else:
                                click_next_button(driver)
                            ok("  OTP resubmitted!")
                            wait_page_load(driver, 4)

                    ok("  MFA setup complete!")

                    # --- 5h: Click "Done" button if it appears ---
                    info("  5h: Looking for Done button...")
                    wait_page_load(driver, 3)
                    done_clicked = False
                    for _ in range(5):
                        # Try common Done/Finish button IDs
                        for btn_id in ["idSIButton9", "idSubmit_ProofUp_Redirect"]:
                            if try_click(driver, By.ID, btn_id, timeout=2):
                                done_clicked = True
                                ok(f"  Clicked Done ({btn_id})")
                                break
                        if done_clicked:
                            break
                        # Try by button text
                        try:
                            for btn in driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit'], input[type='button']"):
                                btn_text = (btn.text or btn.get_attribute("value") or "").lower()
                                if btn.is_displayed() and any(kw in btn_text for kw in ["done", "finish", "complete", "ok", "got it"]):
                                    driver.execute_script("arguments[0].click();", btn)
                                    done_clicked = True
                                    ok(f"  Clicked '{btn_text.strip()}'")
                                    break
                        except Exception:
                            pass
                        if done_clicked:
                            break
                        time.sleep(2)
                    if done_clicked:
                        wait_page_load(driver, 3)
                    else:
                        info("  No Done button found, continuing...")

                else:
                    warn("  Could not find OTP input field!")
            else:
                warn("  No secret key - waiting for manual MFA (120s)...")
                for _ in range(60):
                    time.sleep(2)
                    if is_login_done(driver):
                        break

            info("=" * 50)
        else:
            info("[Step 5] No MFA required - skipping")

        # ========== STEP 6: Finish Sign-in ==========
        info("[Step 6] Completing sign-in...")

        # Click through remaining pages (Stay signed in, OTP, confirmation, etc.)
        for _ in range(10):
            wait_page_load(driver, 3)
            page_text = get_page_text(driver)

            # Check if we reached admin portal or device code completion
            url = driver.current_url
            if "admin.microsoft.com" in url and "login" not in url.lower():
                ok("  Admin portal reached!")
                break
            if "you have signed in" in page_text or "you're all set" in page_text:
                ok("  Device code auth confirmed!")
                break

            # OTP/MFA prompt - use saved secret key from column H
            otp_keywords = ["enter the code", "enter code", "verify your identity",
                           "verification code", "6-digit", "approve sign-in"]
            if saved_secret_key and any(kw in page_text for kw in otp_keywords):
                info("  OTP prompted, entering code from saved secret...")
                otp_code = generate_otp(saved_secret_key)
                if otp_code:
                    otp_field = find_otp_input(driver)
                    if otp_field:
                        safe_type(otp_field, otp_code)
                        time.sleep(0.5)
                        verify_btn = try_find(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3)
                        if verify_btn:
                            try:
                                verify_btn.click()
                            except Exception:
                                driver.execute_script("arguments[0].click();", verify_btn)
                        else:
                            click_next_button(driver)
                        ok("  OTP submitted")
                        wait_page_load(driver, 3)
                        continue

            # "Stay signed in?" -> click Yes
            if "stay signed in" in page_text or "KmsiDescription" in driver.page_source:
                try_click(driver, By.ID, "idSIButton9", timeout=3)
                info("  Clicked Yes - Stay signed in")
                continue

            # "Are you trying to sign in?" -> click Continue
            if "are you trying to sign in" in page_text:
                try_click(driver, By.ID, "idSIButton9", timeout=3)
                info("  Clicked Continue")
                continue

            # Any visible Next/Continue button
            if try_find(driver, By.ID, "idSIButton9", timeout=2):
                try_click(driver, By.ID, "idSIButton9", timeout=2)
                info("  Clicked Next")
                continue

            # Done pages
            if "successfully" in page_text or "signed in" in page_text or "you're all set" in page_text:
                ok("  Login complete!")
                break

        ok("[Step 6] Login completed!")

        if saved_secret_key:
            info(f"  MFA Secret Key: {saved_secret_key}")

        return password_changed, saved_secret_key

    except Exception as e:
        err(f"Browser error: {e}")
        try:
            ss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error_screenshot.png")
            driver.save_screenshot(ss_path)
            info(f"  Screenshot: {ss_path}")
        except Exception:
            pass
        raise
    finally:
        driver.quit()
        info("Chrome closed")


# --- Azure CLI ---
AZ_PATHS = [
    r"C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
    r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
]

def find_az():
    # Check Windows paths
    for path in AZ_PATHS:
        if os.path.exists(path):
            return path
    # Check Linux/Mac - try 'which' first (more portable)
    for cmd in ["which", "where"]:
        try:
            r = subprocess.run([cmd, "az"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().split("\n")[0]
        except Exception:
            pass
    # Direct path check
    if os.path.exists("/usr/bin/az"):
        return "/usr/bin/az"
    if os.path.exists("/usr/local/bin/az"):
        return "/usr/local/bin/az"
    return None

def az_command(az_path, args):
    cmd = [az_path] + args
    info(f"  $ az {' '.join(args)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout or "az command failed")
    return r.stdout.strip()

def safe_json_loads(raw, label=""):
    """Safely parse JSON, retrying az command if empty."""
    if not raw or not raw.strip():
        raise RuntimeError(f"Empty response from az CLI{' (' + label + ')' if label else ''}")
    try:
        return json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"Invalid JSON from az CLI{' (' + label + ')' if label else ''}: {str(e)[:100]}")

def get_graph_token(az_path):
    tenant = os.environ.get("_AZ_TENANT", "")
    # Try with tenant first
    if tenant:
        try:
            raw = az_command(az_path, ["account", "get-access-token",
                                       "--resource", "https://graph.microsoft.com",
                                       "--tenant", tenant, "-o", "json"])
            return safe_json_loads(raw, "get-access-token tenant")["accessToken"]
        except Exception:
            pass
    # Try with domain
    domain = os.environ.get("_AZ_DOMAIN", "")
    if domain:
        try:
            raw = az_command(az_path, ["account", "get-access-token",
                                       "--resource", "https://graph.microsoft.com",
                                       "--tenant", domain, "-o", "json"])
            return safe_json_loads(raw, "get-access-token domain")["accessToken"]
        except Exception:
            pass
    # Try without tenant - retry up to 3 times
    for attempt in range(3):
        try:
            raw = az_command(az_path, ["account", "get-access-token",
                                       "--resource", "https://graph.microsoft.com",
                                       "-o", "json"])
            return safe_json_loads(raw, "get-access-token")["accessToken"]
        except Exception as e:
            if attempt < 2:
                warn(f"  Token attempt {attempt+1} failed, retrying...")
                time.sleep(2)
            else:
                raise

def get_tenant_id(az_path):
    # Retry up to 5 times for az account show with increasing delays
    for attempt in range(5):
        try:
            raw = az_command(az_path, ["account", "show", "-o", "json"])
            return safe_json_loads(raw, "account show")["tenantId"]
        except Exception:
            if attempt < 4:
                delay = 3 + attempt * 2  # 3, 5, 7, 9 seconds
                warn(f"  Tenant ID attempt {attempt+1} failed, retrying in {delay}s...")
                time.sleep(delay)
                continue
            # Final fallback: try listing accounts
            try:
                raw = az_command(az_path, ["account", "list", "-o", "json"])
                accounts = safe_json_loads(raw, "account list")
                if accounts:
                    # Return the last (most recent) account
                    return accounts[-1]["tenantId"]
            except Exception:
                pass
            raise RuntimeError("No Azure account found. Login may have failed.")


def do_az_login(az_path, email, password, new_password=None, mfa_secret=None):
    """
    Flow:
    1. Start 'az login --use-device-code' in background -> get device code
    2. Open Selenium Chrome incognito -> microsoft.com/devicelogin
    3. Enter device code -> login (email, password, MFA) all in one browser
    4. If mfa_secret provided, uses it to generate OTP (skips MFA setup)
    5. az CLI picks up token automatically
    """
    domain = email.split("@")[1] if "@" in email else ""

    output_lines = []
    def read_output(pipe):
        for line in iter(pipe.readline, ""):
            output_lines.append(line)
            info(f"  az: {line.strip()}")

    # ===== Start az login --use-device-code =====
    cmd_args = [az_path, "login", "--use-device-code", "--allow-no-subscriptions"]
    if domain:
        cmd_args.extend(["--tenant", domain])
    info(f"  Starting: az login --use-device-code --allow-no-subscriptions --tenant {domain}")

    proc = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)

    t_err = threading.Thread(target=read_output, args=(proc.stderr,))
    t_err.daemon = True
    t_err.start()

    # Wait for device code
    device_code = None
    start = time.time()
    while time.time() - start < 30:
        for line in output_lines:
            match = re.search(r"enter the code\s+(\S+)\s+to authenticate", line, re.IGNORECASE)
            if match:
                device_code = match.group(1)
                break
        if device_code:
            break
        time.sleep(0.5)

    if not device_code:
        proc.kill()
        raise RuntimeError(f"No device code from az login. Output: {''.join(output_lines)[:300]}")

    ok(f"Got device code: {device_code}")

    # ===== Open incognito browser -> device login -> full login + MFA =====
    info("Opening incognito browser for device code + login + MFA...")
    password_changed, secret_key = browser_login(email, password, new_password, device_code=device_code, mfa_secret=mfa_secret)
    if password_changed:
        ok("Password was changed during login")

    # Wait for az login to complete
    info("Waiting for az login to complete...")
    login_success = False
    try:
        # Read stdout too (az login outputs JSON to stdout on success)
        stdout_data, _ = proc.communicate(timeout=120)
        if proc.returncode == 0:
            ok("Azure CLI login successful!")
            login_success = True
            # Give az CLI time to flush token cache to disk
            info("  Waiting for token cache to flush...")
            time.sleep(5)
        else:
            warn(f"az login exited with code {proc.returncode}")
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        warn("az login timed out")

    # Fallback: try direct password login
    if not login_success:
        actual_pw = new_password if password_changed and new_password else password
        info("  Trying direct password login as fallback...")
        try:
            az_command(az_path, ["login", "--allow-no-subscriptions",
                                 "--tenant", domain,
                                 "-u", email, "-p", actual_pw])
            ok("Direct login successful")
            time.sleep(3)
        except Exception:
            warn("All login attempts failed - will try to continue")

    return password_changed, secret_key


# --- Graph API helpers ---
GRAPH_URL = "https://graph.microsoft.com/v1.0"
GRAPH_API_APP_ID = "00000003-0000-0000-c000-000000000000"
EXCHANGE_API_APP_ID = "00000002-0000-0ff1-ce00-000000000000"
EXCHANGE_ADMIN_ROLE_ID = "29232cdf-9323-42fd-ade2-1d097af3e4de"

REQUIRED_GRAPH_PERMISSIONS = [
    "Policy.ReadWrite.ConditionalAccess",
    "Policy.ReadWrite.AuthenticationMethod",
    "Policy.ReadWrite.SecurityDefaults",
    "Policy.Read.All",
    "Domain.ReadWrite.All",
    "User.ReadWrite.All",
    "UserAuthenticationMethod.ReadWrite.All",
    "Organization.ReadWrite.All",
    "Directory.ReadWrite.All",
    "Mail.ReadWrite",
    "Mail.Send",
]
REQUIRED_GRAPH_DELEGATED = ["SMTP.Send"]
REQUIRED_EXCHANGE_PERMISSIONS = ["full_access_as_app", "Exchange.ManageAsApp"]


def api_get(token, url):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 400:
        raise RuntimeError(f"GET {url} - {r.status_code}: {r.text[:200]}")
    text = r.text.strip()
    if not text:
        return {}
    try:
        return r.json()
    except Exception:
        return {}

def api_post(token, url, body):
    r = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    if r.status_code >= 400:
        raise RuntimeError(f"POST {url} - {r.status_code}: {r.text[:300]}")
    text = r.text.strip()
    if not text:
        return {}
    try:
        return r.json()
    except Exception:
        return {}

def api_patch(token, url, body):
    r = requests.patch(url, json=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    if r.status_code >= 400:
        raise RuntimeError(f"PATCH {url} - {r.status_code}: {r.text[:300]}")
    text = r.text.strip()
    if not text:
        return {}
    try:
        return r.json()
    except Exception:
        return {}

def lookup_sp_roles(token, app_id):
    data = api_get(token, f"{GRAPH_URL}/servicePrincipals?$filter=appId eq '{app_id}'&$select=id,appId,appRoles,oauth2PermissionScopes")
    if not data.get("value"):
        raise RuntimeError(f"SP not found for {app_id}")
    sp = data["value"][0]
    roles = {r["value"]: r["id"] for r in sp.get("appRoles", [])}
    scopes = {s["value"]: s["id"] for s in sp.get("oauth2PermissionScopes", [])}
    return sp["id"], roles, scopes

def setup_app_registration(token, email, sheet_row=None, apps_script_url=None, tenant_id=None, secret_key=None):
    """Create app, secret, permissions, consent, role."""
    app_name = f"AppReg-{email.split('@')[0]}-{int(time.time())}"

    # Create app
    info("Creating App Registration...")
    result = api_post(token, f"{GRAPH_URL}/applications", {"displayName": app_name, "signInAudience": "AzureADMyOrg"})
    app_oid = result["id"]
    client_id = result["appId"]
    ok(f"  App: {client_id}")

    # Write Client ID to sheet immediately
    if sheet_row:
        write_to_google_sheet(
            apps_script_url, "credentials", sheet_row,
            tenantId=tenant_id or "",
            clientId=client_id,
            secretKey=secret_key or "",
            status="CREATING SECRET",
        )

    # Create service principal
    info("Creating Service Principal...")
    try:
        sp = api_post(token, f"{GRAPH_URL}/servicePrincipals", {"appId": client_id})
        sp_id = sp["id"]
    except RuntimeError as e:
        if "already exists" in str(e).lower():
            data = api_get(token, f"{GRAPH_URL}/servicePrincipals?$filter=appId eq '{client_id}'&$select=id")
            sp_id = data["value"][0]["id"]
        else:
            raise
    ok(f"  SP: {sp_id}")

    # Create secret
    info("Creating Client Secret...")
    secret_result = api_post(token, f"{GRAPH_URL}/applications/{app_oid}/addPassword", {
        "passwordCredential": {"displayName": "AutoSecret", "endDateTime": "2028-12-31T23:59:59Z"}
    })
    client_secret = secret_result["secretText"]
    ok(f"  Secret: {client_secret[:10]}...")

    # Write Client ID + Client Secret to sheet immediately
    if sheet_row:
        write_to_google_sheet(
            apps_script_url, "credentials", sheet_row,
            tenantId=tenant_id or "",
            clientId=client_id,
            clientSecret=client_secret,
            secretKey=secret_key or "",
            status="GRANTING PERMISSIONS",
        )

    # Lookup permission IDs
    info("Looking up permissions...")
    graph_sp_id, graph_roles, graph_scopes = lookup_sp_roles(token, GRAPH_API_APP_ID)
    exchange_sp_id, exchange_roles, _ = lookup_sp_roles(token, EXCHANGE_API_APP_ID)

    # Build required access
    graph_access = []
    for p in REQUIRED_GRAPH_PERMISSIONS:
        rid = graph_roles.get(p)
        if rid:
            graph_access.append({"id": rid, "type": "Role"})
    for p in REQUIRED_GRAPH_DELEGATED:
        sid = graph_scopes.get(p)
        if sid:
            graph_access.append({"id": sid, "type": "Scope"})
    exchange_access = []
    for p in REQUIRED_EXCHANGE_PERMISSIONS:
        rid = exchange_roles.get(p)
        if rid:
            exchange_access.append({"id": rid, "type": "Role"})

    req_access = []
    if graph_access:
        req_access.append({"resourceAppId": GRAPH_API_APP_ID, "resourceAccess": graph_access})
    if exchange_access:
        req_access.append({"resourceAppId": EXCHANGE_API_APP_ID, "resourceAccess": exchange_access})

    api_patch(token, f"{GRAPH_URL}/applications/{app_oid}", {"requiredResourceAccess": req_access})
    ok("  Permissions added to manifest")

    # Grant admin consent
    info("Granting admin consent...")
    granted = 0
    for p in REQUIRED_GRAPH_PERMISSIONS:
        rid = graph_roles.get(p)
        if not rid:
            continue
        try:
            api_post(token, f"{GRAPH_URL}/servicePrincipals/{sp_id}/appRoleAssignments", {
                "principalId": sp_id, "resourceId": graph_sp_id, "appRoleId": rid
            })
            granted += 1
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                granted += 1
            else:
                warn(f"  Failed: {p}")
    for p in REQUIRED_EXCHANGE_PERMISSIONS:
        rid = exchange_roles.get(p)
        if not rid:
            continue
        try:
            api_post(token, f"{GRAPH_URL}/servicePrincipals/{sp_id}/appRoleAssignments", {
                "principalId": sp_id, "resourceId": exchange_sp_id, "appRoleId": rid
            })
            granted += 1
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                granted += 1
            else:
                warn(f"  Failed: {p}")
    ok(f"  Admin consent: {granted} permissions granted")

    # Assign Exchange Administrator role
    info("Assigning Exchange Administrator role...")
    resp = requests.post(
        f"{GRAPH_URL}/roleManagement/directory/roleAssignments",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"principalId": sp_id, "roleDefinitionId": EXCHANGE_ADMIN_ROLE_ID, "directoryScopeId": "/"}
    )
    if resp.status_code in [200, 201, 409]:
        ok("  Exchange Administrator role assigned")
    else:
        warn(f"  Role assignment: {resp.status_code}")

    return app_name, client_id, client_secret


def save_env(tenant_id, client_id, client_secret, secret_key=None):
    """Save credentials to .env file."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    existing = {}
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()

    existing["TENANT_ID"] = tenant_id
    existing["CLIENT_ID"] = client_id
    existing["CLIENT_SECRET"] = client_secret
    if secret_key:
        existing["MFA_SECRET_KEY"] = secret_key

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# Azure App Registration credentials\n")
        f.write(f"TENANT_ID={existing.pop('TENANT_ID')}\n")
        f.write(f"CLIENT_ID={existing.pop('CLIENT_ID')}\n")
        f.write(f"CLIENT_SECRET={existing.pop('CLIENT_SECRET')}\n")
        if "MFA_SECRET_KEY" in existing:
            f.write(f"MFA_SECRET_KEY={existing.pop('MFA_SECRET_KEY')}\n")
        if existing:
            f.write("\n")
            for k, v in existing.items():
                f.write(f"{k}={v}\n")

    ok(f"Saved to {env_path}")


# --- Main ---
def process_one_account(az_path, email, password, new_password, skip_login=False, sheet_row=None, apps_script_url=None, mfa_secret=None):
    """Process a single account: login + MFA + app registration."""
    print()
    info("=" * 60)
    info(f"  Processing: {email}")
    info("=" * 60)
    print()

    # Update sheet status
    if sheet_row:
        write_to_google_sheet(apps_script_url, "rowStatus", sheet_row, status="PROCESSING")

    # Login
    secret_key = None
    password_changed = False
    if not skip_login:
        # Logout previous session and clear cache
        try:
            az_command(az_path, ["logout", "--all"])
        except Exception:
            pass
        try:
            az_command(az_path, ["account", "clear"])
        except Exception:
            pass
        time.sleep(2)  # Let cache clear fully

        if sheet_row:
            write_to_google_sheet(apps_script_url, "rowStatus", sheet_row, status="LOGIN")

        password_changed, secret_key = do_az_login(az_path, email, password, new_password, mfa_secret=mfa_secret)
        if password_changed:
            ok("Password was changed during login")
            password = new_password
            # Update password in sheet
            if sheet_row:
                write_to_google_sheet(apps_script_url, "updatePassword", sheet_row, password=password)
        print()

    # Validate login
    os.environ["_AZ_DOMAIN"] = email.split("@")[1] if "@" in email else ""
    tenant_id = get_tenant_id(az_path)
    os.environ["_AZ_TENANT"] = tenant_id
    ok(f"Tenant: {tenant_id}")

    # Write Tenant ID to sheet immediately
    if sheet_row:
        write_to_google_sheet(
            apps_script_url, "credentials", sheet_row,
            tenantId=tenant_id,
            secretKey=secret_key or "",
            status="APP REGISTRATION",
        )

    token = get_graph_token(az_path)
    ok("Graph API token acquired")
    print()

    # Setup app registration
    info("Setting up App Registration with all permissions...")
    info("-" * 50)
    app_name, client_id, client_secret = setup_app_registration(token, email, sheet_row=sheet_row, apps_script_url=apps_script_url, tenant_id=tenant_id, secret_key=secret_key)
    print()

    # Save locally
    save_env(tenant_id, client_id, client_secret, secret_key)
    print()

    # Final status update
    if sheet_row:
        write_to_google_sheet(
            apps_script_url, "credentials", sheet_row,
            tenantId=tenant_id,
            clientId=client_id,
            clientSecret=client_secret,
            secretKey=secret_key or "",
            status="COMPLETE",
        )

    # Summary
    info("=" * 60)
    ok(f"  DONE: {email}")
    info("=" * 60)
    info(f"  Tenant ID:     {tenant_id}")
    info(f"  Client ID:     {client_id}")
    info(f"  Client Secret: {client_secret[:10]}...")
    info(f"  App Name:      {app_name}")
    if secret_key:
        info(f"  MFA Secret:    {secret_key[:8]}...")
    info("=" * 60)
    print()

    # Step 7: Delete authenticator from security info (separate browser session)
    actual_password = new_password if password_changed and new_password else password
    try:
        delete_authenticator_from_security_info(email, actual_password, secret_key)
    except Exception as e:
        warn(f"Step 7 (delete authenticator) failed: {e}")

    return {
        "email": email,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "app_name": app_name,
        "secret_key": secret_key,
    }


def delete_authenticator_from_security_info(email, password, mfa_secret=None):
    """
    Opens a NEW browser, logs in to mysignins.microsoft.com/security-info,
    finds the authenticator app Delete button, clicks it, confirms OK,
    waits 5 seconds, then closes the browser.
    Called AFTER all az CLI work is done.
    Browser stays open the entire time — only closes after OK + 5s wait.
    """
    info("[Step 7] Deleting authenticator from Security Info...")

    options = ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--incognito")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Try main display first, fallback to headless
    display = os.environ.get("DISPLAY", "")
    if not display:
        try:
            test_result = subprocess.run(["xdpyinfo", "-display", ":1001"],
                capture_output=True, timeout=3)
            if test_result.returncode == 0:
                os.environ["DISPLAY"] = ":1001"
                options.add_argument("--start-maximized")
            else:
                options.add_argument("--headless=new")
        except Exception:
            options.add_argument("--headless=new")
    else:
        options.add_argument("--start-maximized")

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        err(f"  Chrome failed to start: {e}")
        return

    # ---- Login to mysignins.microsoft.com ----
    try:
        info("  Opening security info page...")
        driver.get("https://mysignins.microsoft.com/security-info")
        time.sleep(5)

        # Enter email
        info("  Entering email...")
        email_input = wait_for(driver, By.NAME, "loginfmt", timeout=20)
        time.sleep(1)
        safe_type(email_input, email)
        time.sleep(1)
        try_click(driver, By.ID, "idSIButton9", timeout=5)
        time.sleep(5)

        # Enter password
        info("  Entering password...")
        pwd_input = wait_for(driver, By.NAME, "passwd", timeout=20)
        time.sleep(1)
        safe_type(pwd_input, password)
        time.sleep(1)
        try_click(driver, By.ID, "idSIButton9", timeout=5)
        time.sleep(6)

        # Handle MFA/OTP if prompted
        page_text = get_page_text(driver)
        otp_keywords = ["enter the code", "enter code", "verify your identity",
                       "verification code", "6-digit", "approve sign-in"]

        if mfa_secret and any(kw in page_text for kw in otp_keywords):
            info("  OTP prompted, entering code...")
            otp_code = generate_otp(mfa_secret)
            if otp_code:
                otp_field = find_otp_input(driver)
                if otp_field:
                    safe_type(otp_field, otp_code)
                    time.sleep(1)
                    if not try_click(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3):
                        try_click(driver, By.ID, "idSIButton9", timeout=3)
                    ok("  OTP submitted")
                    time.sleep(5)

        # Handle post-login pages (Stay signed in, etc.)
        for click_round in range(5):
            time.sleep(3)
            page_text = get_page_text(driver)
            url = driver.current_url

            if "security-info" in url or "security info" in page_text:
                ok("  Security info page reached!")
                break

            if "stay signed in" in page_text:
                try_click(driver, By.ID, "idSIButton9", timeout=3)
                info("  Clicked Yes - Stay signed in")
                continue

            if "are you trying to sign in" in page_text:
                try_click(driver, By.ID, "idSIButton9", timeout=3)
                info("  Clicked Continue")
                continue

            if try_click(driver, By.ID, "idSIButton9", timeout=2):
                info("  Clicked Next/Yes")
                continue

            if try_click(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=2):
                info("  Clicked ProofUp redirect")
                continue

        # Make sure we're on security info
        url = driver.current_url
        if "security-info" not in url:
            driver.get("https://mysignins.microsoft.com/security-info")
            time.sleep(8)

        time.sleep(3)
    except Exception as e:
        err(f"  Step 7 login error: {e}")
        # Don't close browser yet on login error, try to continue
        pass

    # ---- Find and click Delete → OK → wait 5s → close browser ----
    clicked_ok = False
    try:
        info("  Looking for Delete button...")

        for attempt in range(5):
            # Approach 1: Find Delete/Remove text elements
            try:
                delete_elements = driver.find_elements(By.XPATH,
                    "//*[contains(text(),'Delete') or contains(text(),'delete') or contains(text(),'Remove') or contains(text(),'remove')]"
                )
                for el in delete_elements:
                    el_text = el.text.strip().lower()
                    if el_text in ["delete", "remove"] and el.is_displayed():
                        info(f"  Found: '{el.text}' - clicking Delete...")
                        driver.execute_script("arguments[0].click();", el)
                        time.sleep(2)

                        # Click OK/Yes in confirmation popup
                        for confirm_text in ["OK", "Yes", "Confirm", "Delete", "Remove"]:
                            try:
                                confirm_btns = driver.find_elements(By.XPATH,
                                    f"//button[contains(text(),'{confirm_text}')] | //input[@value='{confirm_text}']"
                                )
                                for btn in confirm_btns:
                                    if btn.is_displayed():
                                        driver.execute_script("arguments[0].click();", btn)
                                        ok(f"  Clicked OK ({confirm_text})")
                                        clicked_ok = True
                                        break
                            except Exception:
                                pass
                            if clicked_ok:
                                break

                        if clicked_ok:
                            break
                if clicked_ok:
                    break
            except Exception as e:
                info(f"  Attempt {attempt+1} error: {e}")

            # Approach 2: Try aria-label buttons
            if not clicked_ok:
                try:
                    del_btns = driver.find_elements(By.CSS_SELECTOR,
                        "button[aria-label*='Delete'], button[aria-label*='delete'], "
                        "button[aria-label*='Remove'], a[aria-label*='Delete']"
                    )
                    for btn in del_btns:
                        if btn.is_displayed():
                            label = btn.get_attribute("aria-label") or btn.text
                            info(f"  Clicking: {label}")
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(2)
                            for confirm_sel in ["button.ms-Button--primary", "button[aria-label*='Yes']",
                                               "button[aria-label*='Confirm']", "button[aria-label*='Delete']",
                                               "button[aria-label*='OK']"]:
                                if try_click(driver, By.CSS_SELECTOR, confirm_sel, timeout=2):
                                    ok("  Deletion confirmed")
                                    clicked_ok = True
                                    break
                            if clicked_ok:
                                break
                except Exception:
                    pass

            if clicked_ok:
                break

            info(f"  Attempt {attempt+1}: retrying...")
            time.sleep(2)

        if not clicked_ok:
            page_text = get_page_text(driver)
            if "authenticator" not in page_text:
                ok("[Step 7] No authenticator found (already clean)")
            else:
                warn("[Step 7] Could not delete authenticator")

    except Exception as e:
        err(f"  Step 7 delete error: {e}")

    # ---- OK clicked → wait 10 seconds → THEN close browser ----
    if clicked_ok:
        info("  Waiting 10 seconds after OK...")
        time.sleep(10)
        ok("[Step 7] Authenticator app DELETED!")

    # NOW close the browser
    try:
        driver.quit()
    except Exception:
        pass
    info("  Step 7 browser closed")


def main():
    # Load .env for APPS_SCRIPT_URL
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    parser = argparse.ArgumentParser(description="Microsoft Login + MFA Auto-Setup + App Registration")
    parser.add_argument("--email", help="Admin email")
    parser.add_argument("--password", help="Admin password")
    parser.add_argument("--new-password", default=None, help="New password (if forced change)")
    parser.add_argument("--sheet", default=None, help="Google Sheet ID (B=email, C=password, D=new password)")
    parser.add_argument("--apps-script-url", default=None, help="Google Apps Script web app URL")
    parser.add_argument("--row", type=int, default=None, help="Process only this row number from sheet (1-based)")
    parser.add_argument("--app-name", default=None, help="App name")
    parser.add_argument("--skip-login", action="store_true", help="Skip login (use existing az session)")
    args = parser.parse_args()

    # Find Azure CLI
    az_path = find_az()
    if not az_path:
        err("Azure CLI not found! Install: https://aka.ms/installazurecliwindows")
        sys.exit(1)
    ok(f"Azure CLI: {az_path}")

    # Resolve Apps Script URL
    script_url = args.apps_script_url or os.environ.get("APPS_SCRIPT_URL", "")

    # Get credentials from Sheet or command line
    if args.sheet:
        creds_list = read_from_google_sheet(args.sheet, script_url)
        if not creds_list:
            err("No credentials found in Google Sheet")
            sys.exit(1)

        # Filter by row if specified (uses sheet row number from response)
        if args.row:
            creds_list = [c for c in creds_list if c.get("row") == args.row]
            if not creds_list:
                err(f"Row {args.row} not found in sheet data")
                sys.exit(1)
            info(f"Processing row {args.row} only")

        # Process each account from sheet
        results = []
        for i, cred in enumerate(creds_list):
            sheet_row = cred.get("row")
            info(f"\n>>> Account {i+1}/{len(creds_list)}: {cred['email']} (sheet row {sheet_row})")
            try:
                result = process_one_account(
                    az_path,
                    cred["email"],
                    cred["password"],
                    cred.get("new_password") or args.new_password,
                    skip_login=args.skip_login,
                    sheet_row=sheet_row,
                    apps_script_url=script_url,
                    mfa_secret=cred.get("mfa_secret") or None,
                )
                results.append(result)
            except Exception as e:
                err(f"Failed for {cred['email']}: {e}")
                # Write error to sheet
                if sheet_row:
                    write_to_google_sheet(script_url, "error", sheet_row, message=str(e))
                continue

        # Final summary
        print()
        info("=" * 60)
        ok(f"  COMPLETED: {len(results)}/{len(creds_list)} accounts")
        info("=" * 60)
        for r in results:
            info(f"  {r['email']} -> {r['client_id']}")
        info("")
        info("  Next: python tenant_setup_automation.py --use-cli")
        info("=" * 60)

    else:
        # Single account from command line
        email = args.email
        password = args.password
        new_password = args.new_password

        if not args.skip_login and (not email or not password):
            err("Provide --email + --password, or --sheet <ID>, or --skip-login")
            sys.exit(1)

        result = process_one_account(az_path, email, password, new_password, args.skip_login)

        info("")
        info("  Next: python tenant_setup_automation.py --use-cli")
        info("=" * 60)


if __name__ == "__main__":
    main()
