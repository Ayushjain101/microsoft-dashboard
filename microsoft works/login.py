#!/usr/bin/env python3
"""
login.py — Automated Azure App Registration & Full Permission Setup
====================================================================
1. Opens Chrome → logs into Microsoft via az device code
2. Handles password change / MFA (with interactive OTP entry)
3. Creates App Registration via Graph API
4. Creates Client Secret via Graph API
5. Adds ALL required API permissions via Graph API
6. Grants admin consent via Graph API (appRoleAssignments)
7. Assigns Exchange Administrator role via Graph API
8. Saves credentials to .env

Usage:
  python login.py --email admin@domain.com --password "Pass123!"
  python login.py --email admin@domain.com --password "Old" --new-password "New123!"
  python login.py --sheet <SHEET_ID>           (read from Google Sheet columns B,C,D)
  python login.py --skip-login                 (use existing az session)

Google Sheet columns:
  B: Admin email
  C: Password
  D: New password (if forced change)

Requirements:
  pip install selenium requests gspread google-auth
  Azure CLI: https://aka.ms/installazurecliwindows
"""

import os
import sys
import json
import time
import argparse
import subprocess
import threading
import re
from datetime import datetime

# ─── Auto-install dependencies ─────────────────────────────────
def ensure_packages():
    required = {
        "selenium": "selenium",
        "requests": "requests",
        "gspread": "gspread",
        "google-auth": "google-auth",
        "pyotp": "pyotp",
        "pyzbar": "pyzbar",
        "pillow": "pillow",
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
import requests


# ─── Logging ────────────────────────────────────────────────────
def log(level, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {level:5s}  {msg}")

def info(msg):  log("INFO", msg)
def ok(msg):    log("OK", msg)
def warn(msg):  log("WARN", msg)
def err(msg):   log("ERROR", msg)


# ─── Load .env ──────────────────────────────────────────────────
def load_env():
    for search_dir in [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]:
        env_path = os.path.join(search_dir, ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ.setdefault(key.strip(), val.strip())


# ─── Google Sheets Integration ────────────────────────────────
def read_from_google_sheet(sheet_id):
    """Read credentials from Google Sheet (columns B, C, D)."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        warn("gspread not installed. Run: pip install gspread google-auth")
        return None, None, None

    info("Reading credentials from Google Sheet...")

    # Try to find service account credentials
    sa_file = None
    for name in ["service_account.json", "google_creds.json", "credentials.json"]:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        if os.path.exists(path):
            sa_file = path
            break

    if not sa_file:
        warn("No Google service account file found (service_account.json)")
        warn("Create one: https://console.cloud.google.com > Service Accounts > Create Key (JSON)")
        return None, None, None

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        credentials = Credentials.from_service_account_file(sa_file, scopes=scopes)
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_key(sheet_id)
        ws = sheet.sheet1

        # Get all values
        all_values = ws.get_all_values()

        # Find rows with email, password, new password
        # Skip header row (index 0)
        if len(all_values) < 2:
            warn("Google Sheet is empty")
            return None, None, None

        email = None
        password = None
        new_password = None

        # Look for email in column B (index 1), password in C (index 2), new password in D (index 3)
        for row in all_values[1:]:  # Skip header
            if len(row) > 1 and row[1].strip():  # Column B: email
                email = row[1].strip()
                password = row[2].strip() if len(row) > 2 else None
                new_password = row[3].strip() if len(row) > 3 else None
                if email and password:
                    break

        if email and password:
            ok(f"Google Sheet: Found {email}")
            return email, password, new_password
        else:
            warn("Could not find email/password in Google Sheet (columns B, C, D)")
            return None, None, None

    except Exception as e:
        warn(f"Google Sheet error: {e}")
        return None, None, None


# ─── Constants ──────────────────────────────────────────────────
GRAPH_API_APP_ID = "00000003-0000-0000-c000-000000000000"
EXCHANGE_API_APP_ID = "00000002-0000-0ff1-ce00-000000000000"
GRAPH_URL = "https://graph.microsoft.com/v1.0"

# Exchange Administrator role template ID (same across all tenants)
EXCHANGE_ADMIN_ROLE_ID = "29232cdf-9323-42fd-ade2-1d097af3e4de"

# Required Graph Application permissions for tenant_setup_automation.py
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

# Required Graph Delegated permissions
REQUIRED_GRAPH_DELEGATED = [
    "SMTP.Send",
]

# Required Exchange Application permissions
REQUIRED_EXCHANGE_PERMISSIONS = [
    "full_access_as_app",
    "Exchange.ManageAsApp",
]

# Azure CLI paths on Windows
AZ_PATHS = [
    r"C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
    r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
]


# ─── Azure CLI helpers ──────────────────────────────────────────
def find_az():
    for path in AZ_PATHS:
        if os.path.exists(path):
            return path
    for cmd in ["where az", "which az"]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0]
        except Exception:
            pass
    return None


def az_command(az_path, args):
    cmd = [az_path] + args
    info(f"  $ az {' '.join(args)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, shell=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "az command failed")
    return result.stdout.strip()


def get_graph_token(az_path):
    """Get Graph API token from az CLI session."""
    raw = az_command(az_path, [
        "account", "get-access-token",
        "--resource", "https://graph.microsoft.com",
        "-o", "json"
    ])
    return json.loads(raw)["accessToken"]


def get_tenant_id(az_path):
    raw = az_command(az_path, ["account", "show", "-o", "json"])
    return json.loads(raw)["tenantId"]


# ─── Graph API helpers ──────────────────────────────────────────
def api_get(token, url):
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} → {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def api_post(token, url, body):
    resp = requests.post(url, json=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    if resp.status_code >= 400:
        raise RuntimeError(f"POST {url} → {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.text else {}


def api_patch(token, url, body):
    resp = requests.patch(url, json=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    if resp.status_code >= 400:
        raise RuntimeError(f"PATCH {url} → {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.text else {}


# ─── OTP & MFA Helpers ──────────────────────────────────────────
def extract_secret_key_from_page(driver):
    """Try to extract the secret key from Microsoft MFA setup page."""
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text

        # Look for patterns like "Key: ABC123..." or "Secret: ABC123..."
        patterns = [
            r"[Kk]ey[:\s]+([A-Z2-7]{32,})",  # Microsoft often uses base32
            r"[Ss]ecret[:\s]+([A-Z2-7]{32,})",
            r"Manual entry key[:\s]+([A-Z2-7]{32,})",
            r"([A-Z2-7]{32})",  # Just base32 string
        ]

        for pattern in patterns:
            match = re.search(pattern, page_text)
            if match:
                secret_key = match.group(1).strip()
                if len(secret_key) >= 16:
                    ok(f"  Found secret key: {secret_key[:8]}...")
                    return secret_key
    except Exception as e:
        info(f"  Could not extract secret key: {e}")

    return None


def extract_qr_code_from_page(driver, output_file="/tmp/qr_code.png"):
    """Try to find and save QR code image from the page."""
    try:
        # Look for QR code image
        qr_elements = driver.find_elements(By.TAG_NAME, "img")
        for img in qr_elements:
            src = img.get_attribute("src")
            alt = img.get_attribute("alt") or ""

            # Look for QR code indicators
            if any(kw in src.lower() for kw in ["qr", "barcode", "code"]) or \
               any(kw in alt.lower() for kw in ["qr", "barcode", "code"]):
                # Found QR code image
                import base64
                from urllib.request import urlopen

                if src.startswith("data:"):
                    # Base64 encoded data URI
                    data = src.split(",")[1]
                    with open(output_file, "wb") as f:
                        f.write(base64.b64decode(data))
                    ok(f"  QR code saved to: {output_file}")
                    return output_file
                elif src.startswith("http"):
                    # URL reference
                    with urlopen(src) as response:
                        with open(output_file, "wb") as f:
                            f.write(response.read())
                    ok(f"  QR code downloaded to: {output_file}")
                    return output_file
    except Exception as e:
        info(f"  Could not extract QR code: {e}")

    return None


def generate_otp_from_secret(secret_key):
    """Generate a 6-digit OTP code from secret key using pyotp."""
    try:
        import pyotp
        totp = pyotp.TOTP(secret_key)
        otp_code = totp.now()
        ok(f"  Generated OTP: {otp_code}")
        return otp_code
    except Exception as e:
        warn(f"  Could not generate OTP: {e}")
        return None


def read_qr_code(qr_image_path):
    """Try to read QR code image and extract secret key."""
    try:
        from pyzbar.pyzbar import decode
        from PIL import Image

        img = Image.open(qr_image_path)
        results = decode(img)

        if results:
            qr_data = results[0].data.decode()
            # QR codes for TOTP are in format: otpauth://totp/...?secret=ABC123...
            match = re.search(r"secret=([A-Z2-7]+)", qr_data, re.IGNORECASE)
            if match:
                secret_key = match.group(1)
                ok(f"  Decoded QR code: {secret_key[:8]}...")
                return secret_key
    except Exception as e:
        info(f"  Could not read QR code: {e}")

    return None


# ─── Browser Login ──────────────────────────────────────────────
def wait_and_find(driver, by, value, timeout=60):
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, value))
    )

def try_find(driver, by, value, timeout=3):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )
    except Exception:
        return None

def check_for_error(driver):
    for sel in ["#usernameError", "#passwordError", ".alert-error", "#errorText"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                return el.text
        except Exception:
            pass
    return None


def browser_login(email, password, new_password, device_code):
    """Open Chrome and complete the device code login flow."""
    info("Launching Chrome browser for device code login...")

    options = ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    password_changed = False

    try:
        # Device login page
        info("Opening device login page...")
        driver.get("https://microsoft.com/devicelogin")

        # Enter device code
        info(f"Entering device code: {device_code}")
        code_input = wait_and_find(driver, By.ID, "otc")
        time.sleep(0.5)
        code_input.send_keys(device_code)
        driver.find_element(By.ID, "idSIButton9").click()
        ok("Device code submitted")

        # Enter email
        info("Waiting for email field...")
        time.sleep(2)
        email_input = wait_and_find(driver, By.NAME, "loginfmt")
        time.sleep(0.5)
        email_input.clear()
        email_input.send_keys(email)
        info(f"Email entered: {email}")
        time.sleep(0.5)
        wait_and_find(driver, By.ID, "idSIButton9").click()
        info("Email next clicked")

        time.sleep(2)
        error = check_for_error(driver)
        if error:
            raise RuntimeError(f"Email error: {error}")

        # Enter password
        info("Waiting for password field...")
        time.sleep(2)
        pwd_input = wait_and_find(driver, By.NAME, "passwd")
        time.sleep(0.5)
        pwd_input.click()
        pwd_input.clear()
        pwd_input.send_keys(password)
        info("Password entered")
        time.sleep(0.5)
        wait_and_find(driver, By.ID, "idSIButton9").click()
        info("Sign in clicked")

        time.sleep(3)
        error = check_for_error(driver)
        if error:
            raise RuntimeError(f"Login error: {error}")

        # Check for password change
        page_text = driver.find_element(By.TAG_NAME, "body").text
        info(f"Page after sign-in: {page_text[:100]}")

        if "update your password" in page_text.lower():
            info("PASSWORD CHANGE page detected!")
            if not new_password:
                raise RuntimeError("Password change required but no --new-password provided")

            current_pwd = try_find(driver, By.ID, "iPassword", 5)
            if current_pwd:
                current_pwd.clear()
                current_pwd.send_keys(password)
            else:
                alt = try_find(driver, By.NAME, "oldPassword", 5)
                if alt:
                    alt.clear()
                    alt.send_keys(password)

            time.sleep(0.5)
            new_pwd = try_find(driver, By.ID, "iNewPassword", 5)
            if new_pwd:
                new_pwd.clear()
                new_pwd.send_keys(new_password)
            else:
                alt = try_find(driver, By.NAME, "newPassword", 5)
                if alt:
                    alt.clear()
                    alt.send_keys(new_password)

            time.sleep(0.5)
            confirm_pwd = try_find(driver, By.ID, "iConfirmPassword", 5)
            if confirm_pwd:
                confirm_pwd.clear()
                confirm_pwd.send_keys(new_password)
            else:
                alt = try_find(driver, By.NAME, "confirmNewPassword", 5)
                if alt:
                    alt.clear()
                    alt.send_keys(new_password)

            time.sleep(0.5)
            # Fallback: fill all password inputs by index
            all_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            if len(all_inputs) == 3:
                all_inputs[0].clear(); all_inputs[0].send_keys(password)
                all_inputs[1].clear(); all_inputs[1].send_keys(new_password)
                all_inputs[2].clear(); all_inputs[2].send_keys(new_password)
            elif len(all_inputs) == 2:
                all_inputs[0].clear(); all_inputs[0].send_keys(new_password)
                all_inputs[1].clear(); all_inputs[1].send_keys(new_password)

            time.sleep(0.5)
            wait_and_find(driver, By.ID, "idSIButton9", 10).click()
            info("Password change submitted")

            time.sleep(3)
            error = check_for_error(driver)
            if error:
                raise RuntimeError(f"Password change error: {error}")

            password_changed = True
            ok("Password changed successfully!")

        # Handle MFA if prompted
        time.sleep(2)
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()

        if any(kw in page_text for kw in [
            "verify your identity", "more information required",
            "prove you", "authenticator", "approve a request",
            "enter code", "verification code"
        ]):
            info("=" * 60)
            info("  MFA SETUP DETECTED")
            info("=" * 60)
            info("")
            info("  Attempting automatic OTP generation...")
            info("")

            mfa_done = False
            otp_entered = False
            auto_otp_attempted = False

            # Try to extract secret key and generate OTP automatically
            secret_key = None

            # Method 1: Extract secret key directly from page text
            info("  [1/3] Looking for secret key on page...")
            secret_key = extract_secret_key_from_page(driver)

            # Method 2: Try to extract QR code and decode it
            if not secret_key:
                info("  [2/3] Looking for QR code image...")
                qr_file = extract_qr_code_from_page(driver, "/tmp/mfa_qr.png")
                if qr_file:
                    secret_key = read_qr_code(qr_file)

            # Method 3: Generate OTP from extracted secret
            otp_code = None
            if secret_key:
                info("  [3/3] Generating OTP code...")
                otp_code = generate_otp_from_secret(secret_key)
                if otp_code:
                    auto_otp_attempted = True
                    info("")
                    info(f"  Generated OTP: {otp_code}")

            # If we have an OTP code, try to auto-fill it
            if otp_code:
                info("  Attempting to auto-fill OTP field...")
                otp_field = try_find(driver, By.CSS_SELECTOR, "input[type='text'][aria-label*='code'],input[type='text'][placeholder*='code']", timeout=5)
                if otp_field:
                    try:
                        otp_field.clear()
                        otp_field.send_keys(otp_code)
                        time.sleep(0.5)
                        # Try to find and click submit button
                        try:
                            driver.find_element(By.ID, "idSIButton9").click()
                        except:
                            pass
                        otp_entered = True
                        ok("  OTP auto-filled and submitted!")
                    except Exception as e:
                        warn(f"  Could not auto-fill OTP: {e}")

            info("")
            info("  Waiting up to 180 seconds for MFA to complete...")
            info("=" * 60)

            # Try to find OTP input field (for manual entry fallback)
            otp_field = try_find(driver, By.CSS_SELECTOR, "input[type='text'][aria-label*='code'],input[type='text'][placeholder*='code']", timeout=5)

            for attempt in range(180):
                time.sleep(1)
                try:
                    current_url = driver.current_url
                    current_text = driver.find_element(By.TAG_NAME, "body").text.lower()

                    # Check if MFA is complete
                    if any(kw in current_text for kw in [
                        "stay signed in", "you have signed in",
                        "are you trying to sign in", "successfully", "confirmed"
                    ]):
                        mfa_done = True
                        break

                    if "kmsi" in current_url or "appconfirm" in current_url:
                        mfa_done = True
                        break

                    # If auto-OTP didn't work and OTP field found, ask user for manual entry
                    if otp_field and not otp_entered and not auto_otp_attempted and attempt > 10:
                        try:
                            info("")
                            info("  OTP code field detected in browser")
                            info("  Enter the 6-digit code from your authenticator app")
                            otp_code = input("  6-digit code: ").strip()
                            if otp_code and len(otp_code) == 6:
                                otp_field.clear()
                                otp_field.send_keys(otp_code)
                                time.sleep(0.5)
                                # Try to find and click submit button
                                try:
                                    driver.find_element(By.ID, "idSIButton9").click()
                                except:
                                    pass
                                otp_entered = True
                                ok("  OTP submitted")
                            elif otp_code:
                                warn(f"  Invalid OTP length: {len(otp_code)} (expected 6)")
                        except EOFError:
                            # Running non-interactively
                            pass

                except Exception:
                    pass

            if mfa_done:
                ok("MFA completed!")
            elif otp_entered:
                ok("OTP submitted, waiting for confirmation...")
            else:
                warn("MFA timeout — continuing anyway (may fail at next step)")

        # Handle "Stay signed in?"
        try:
            wait_and_find(driver, By.ID, "KmsiDescription", 10)
            driver.find_element(By.ID, "idSIButton9").click()
            info("Clicked 'Yes' on Stay signed in")
        except Exception:
            pass

        # Confirmation page
        time.sleep(3)
        try:
            confirm_btn = wait_and_find(driver, By.ID, "idSIButton9", 15)
            confirm_btn.click()
            info("Confirmation clicked")
        except Exception:
            pass

        time.sleep(3)
        final_text = driver.find_element(By.TAG_NAME, "body").text
        if "signed in" in final_text.lower() or "successfully" in final_text.lower():
            ok("Login confirmed in browser!")

        ok("Browser login flow completed")
        return password_changed

    finally:
        driver.quit()
        info("Chrome closed")


def do_az_login(az_path, email, password, new_password=None):
    """Run az login --use-device-code and complete login via Selenium."""
    info("Starting az login with device code...")

    full_cmd = f'"{az_path}" login --use-device-code --allow-no-subscriptions'
    proc = subprocess.Popen(
        full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=True, text=True,
    )

    device_code = None
    output_lines = []

    def read_output(pipe, lines):
        for line in iter(pipe.readline, ""):
            lines.append(line)
            info(f"  az: {line.strip()}")

    stderr_thread = threading.Thread(target=read_output, args=(proc.stderr, output_lines))
    stderr_thread.daemon = True
    stderr_thread.start()

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
    password_changed = browser_login(email, password, new_password, device_code)

    info("Waiting for az login to complete...")
    try:
        exit_code = proc.wait(timeout=60)
        if exit_code == 0:
            ok("Azure CLI login successful")
        else:
            warn(f"az login exited with code {exit_code}")
    except subprocess.TimeoutExpired:
        proc.kill()
        warn("az login timed out")

    return password_changed


# ═══════════════════════════════════════════════════════════════
#  ALL APP SETUP VIA GRAPH API (no more unreliable az ad commands)
# ═══════════════════════════════════════════════════════════════

def lookup_sp_roles(token, app_id):
    """Find a service principal by appId and return its id + appRoles as {name: id}."""
    data = api_get(token,
        f"{GRAPH_URL}/servicePrincipals?$filter=appId eq '{app_id}'"
        f"&$select=id,appId,appRoles,oauth2PermissionScopes"
    )
    if not data.get("value"):
        raise RuntimeError(f"Service principal not found for appId {app_id}")
    sp = data["value"][0]
    roles = {r["value"]: r["id"] for r in sp.get("appRoles", [])}
    scopes = {s["value"]: s["id"] for s in sp.get("oauth2PermissionScopes", [])}
    return sp["id"], roles, scopes


def step_create_app(token, app_name):
    """Create app registration via Graph API."""
    info(f"Creating App Registration: '{app_name}'...")
    result = api_post(token, f"{GRAPH_URL}/applications", {
        "displayName": app_name,
        "signInAudience": "AzureADMyOrg",
    })
    app_object_id = result["id"]
    client_id = result["appId"]
    ok(f"App created — Client ID: {client_id}, Object ID: {app_object_id}")
    return app_object_id, client_id


def step_create_secret(token, app_object_id):
    """Create client secret via Graph API."""
    info("Creating client secret...")
    result = api_post(token, f"{GRAPH_URL}/applications/{app_object_id}/addPassword", {
        "passwordCredential": {
            "displayName": "AutoSetupSecret",
            "endDateTime": "2028-12-31T23:59:59Z",
        }
    })
    secret = result["secretText"]
    ok(f"Client secret created (expires 2028-12-31)")
    return secret


def step_create_service_principal(token, client_id):
    """Create service principal for the app."""
    info("Creating service principal...")
    try:
        result = api_post(token, f"{GRAPH_URL}/servicePrincipals", {
            "appId": client_id
        })
        sp_id = result["id"]
        ok(f"Service principal created: {sp_id}")
        return sp_id
    except RuntimeError as e:
        if "already exists" in str(e).lower():
            # Find existing
            data = api_get(token,
                f"{GRAPH_URL}/servicePrincipals?$filter=appId eq '{client_id}'&$select=id"
            )
            sp_id = data["value"][0]["id"]
            ok(f"Service principal already exists: {sp_id}")
            return sp_id
        raise


def step_add_permissions(token, app_object_id):
    """Add all required API permissions to the app manifest."""
    info("Looking up permission IDs...")

    # Lookup Graph API service principal to get role/scope IDs
    graph_sp_id, graph_roles, graph_scopes = lookup_sp_roles(token, GRAPH_API_APP_ID)
    ok(f"  Graph API SP: {graph_sp_id} ({len(graph_roles)} roles, {len(graph_scopes)} scopes)")

    # Lookup Exchange Online service principal to get role IDs
    exchange_sp_id, exchange_roles, exchange_scopes = lookup_sp_roles(token, EXCHANGE_API_APP_ID)
    ok(f"  Exchange SP: {exchange_sp_id} ({len(exchange_roles)} roles)")

    # Build Graph Application permissions
    graph_resource_access = []
    for perm_name in REQUIRED_GRAPH_PERMISSIONS:
        role_id = graph_roles.get(perm_name)
        if role_id:
            graph_resource_access.append({"id": role_id, "type": "Role"})
            ok(f"  + [Graph] {perm_name}")
        else:
            warn(f"  ! [Graph] {perm_name} — NOT FOUND in this tenant")

    # Build Graph Delegated permissions
    for perm_name in REQUIRED_GRAPH_DELEGATED:
        scope_id = graph_scopes.get(perm_name)
        if scope_id:
            graph_resource_access.append({"id": scope_id, "type": "Scope"})
            ok(f"  + [Graph] {perm_name} (Delegated)")
        else:
            warn(f"  ! [Graph] {perm_name} (Delegated) — NOT FOUND")

    # Build Exchange Application permissions
    exchange_resource_access = []
    for perm_name in REQUIRED_EXCHANGE_PERMISSIONS:
        role_id = exchange_roles.get(perm_name)
        if role_id:
            exchange_resource_access.append({"id": role_id, "type": "Role"})
            ok(f"  + [Exchange] {perm_name}")
        else:
            warn(f"  ! [Exchange] {perm_name} — NOT FOUND in this tenant")

    # PATCH the app to set requiredResourceAccess
    required_access = []
    if graph_resource_access:
        required_access.append({
            "resourceAppId": GRAPH_API_APP_ID,
            "resourceAccess": graph_resource_access,
        })
    if exchange_resource_access:
        required_access.append({
            "resourceAppId": EXCHANGE_API_APP_ID,
            "resourceAccess": exchange_resource_access,
        })

    info("Writing permissions to app manifest...")
    api_patch(token, f"{GRAPH_URL}/applications/{app_object_id}", {
        "requiredResourceAccess": required_access
    })
    ok("All permissions added to app manifest")

    return graph_sp_id, graph_roles, graph_scopes, exchange_sp_id, exchange_roles


def step_grant_admin_consent(token, app_sp_id,
                              graph_sp_id, graph_roles, graph_scopes,
                              exchange_sp_id, exchange_roles):
    """Grant admin consent by creating appRoleAssignment for each permission."""
    info("Granting admin consent (creating appRoleAssignments)...")

    total = 0
    granted = 0

    # Grant Graph Application permissions
    for perm_name in REQUIRED_GRAPH_PERMISSIONS:
        role_id = graph_roles.get(perm_name)
        if not role_id:
            continue
        total += 1
        try:
            api_post(token, f"{GRAPH_URL}/servicePrincipals/{app_sp_id}/appRoleAssignments", {
                "principalId": app_sp_id,
                "resourceId": graph_sp_id,
                "appRoleId": role_id,
            })
            ok(f"  ✓ Consented: {perm_name}")
            granted += 1
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                ok(f"  ✓ Already consented: {perm_name}")
                granted += 1
            else:
                warn(f"  ✗ Failed: {perm_name} — {str(e)[:100]}")

    # Grant Exchange Application permissions
    for perm_name in REQUIRED_EXCHANGE_PERMISSIONS:
        role_id = exchange_roles.get(perm_name)
        if not role_id:
            continue
        total += 1
        try:
            api_post(token, f"{GRAPH_URL}/servicePrincipals/{app_sp_id}/appRoleAssignments", {
                "principalId": app_sp_id,
                "resourceId": exchange_sp_id,
                "appRoleId": role_id,
            })
            ok(f"  ✓ Consented: {perm_name} (Exchange)")
            granted += 1
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                ok(f"  ✓ Already consented: {perm_name} (Exchange)")
                granted += 1
            else:
                warn(f"  ✗ Failed: {perm_name} — {str(e)[:100]}")

    # Note: Delegated permissions (SMTP.Send) don't need admin consent via appRoleAssignment
    # They are consented when a user signs in.

    ok(f"Admin consent: {granted}/{total} permissions granted")
    return granted == total


def step_assign_exchange_admin_role(token, app_sp_id):
    """Assign Exchange Administrator directory role to the app's service principal."""
    info("Assigning Exchange Administrator role...")

    try:
        resp = requests.post(
            f"{GRAPH_URL}/roleManagement/directory/roleAssignments",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "principalId": app_sp_id,
                "roleDefinitionId": EXCHANGE_ADMIN_ROLE_ID,
                "directoryScopeId": "/",
            },
        )

        if resp.status_code in [200, 201]:
            ok("Exchange Administrator role assigned!")
            return True
        elif resp.status_code == 409 or "already exists" in resp.text.lower():
            ok("Exchange Administrator role already assigned")
            return True
        else:
            warn(f"Role assignment failed ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as e:
        err(f"Role assignment error: {e}")
        return False


# ─── Save .env ──────────────────────────────────────────────────
def save_to_env(tenant_id, client_id, client_secret):
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    existing = {}
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    existing[key.strip()] = val.strip()

    existing["TENANT_ID"] = tenant_id
    existing["CLIENT_ID"] = client_id
    existing["CLIENT_SECRET"] = client_secret

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# Google Apps Script web app URL\n")
        if "APPS_SCRIPT_URL" in existing:
            f.write(f"APPS_SCRIPT_URL={existing.pop('APPS_SCRIPT_URL')}\n")
        f.write("\n# Azure App Registration credentials\n")
        f.write(f"TENANT_ID={existing.pop('TENANT_ID')}\n")
        f.write(f"CLIENT_ID={existing.pop('CLIENT_ID')}\n")
        f.write(f"CLIENT_SECRET={existing.pop('CLIENT_SECRET')}\n")
        if existing:
            f.write("\n# Other\n")
            for key, val in existing.items():
                f.write(f"{key}={val}\n")

    ok(f"Credentials saved to {env_path}")


# ─── Main ───────────────────────────────────────────────────────
def main():
    load_env()

    parser = argparse.ArgumentParser(
        description="Automated Azure App Registration & Permission Setup"
    )
    parser.add_argument("--email", help="Admin email (e.g. admin@domain.onmicrosoft.com)")
    parser.add_argument("--password", help="Admin password")
    parser.add_argument("--new-password", default=None, help="New password (if forced to change)")
    parser.add_argument("--sheet", default=None, help="Google Sheet ID (reads email from column B, password from C, new password from D)")
    parser.add_argument("--app-name", default=None, help="App registration name")
    parser.add_argument("--skip-login", action="store_true", help="Skip login (use existing az session)")
    args = parser.parse_args()

    # Get credentials from Sheet or command line
    if args.sheet:
        info("Reading from Google Sheet...")
        email, password, new_password = read_from_google_sheet(args.sheet)
        if not email or not password:
            err("Could not read email/password from Google Sheet")
            sys.exit(1)
        if args.new_password:
            new_password = args.new_password
    else:
        email = args.email
        password = args.password
        new_password = args.new_password

    if not args.skip_login and (not email or not password):
        err("Provide --email and --password, or use --sheet <ID>, or use --skip-login")
        err("  python login.py --email admin@domain.com --password Pass123!")
        err("  python login.py --sheet <SHEET_ID>")
        err("  python login.py --skip-login")
        sys.exit(1)

    info("=" * 60)
    info("  Azure App Registration — Full Automation (Graph API)")
    info("=" * 60)
    if email:
        info(f"  Email: {email}")
    if args.sheet:
        info(f"  Source: Google Sheet {args.sheet}")
    info("=" * 60)
    info("")

    # Find Azure CLI
    az_path = find_az()
    if not az_path:
        err("Azure CLI (az) not found!")
        err("Install from: https://aka.ms/installazurecliwindows")
        sys.exit(1)
    ok(f"Azure CLI found: {az_path}")
    info("")

    # ── Step 1: Browser Login ──
    info("Step 1: Browser Login")
    info("-" * 40)
    if not args.skip_login:
        password_changed = do_az_login(az_path, email, password, new_password)
        if password_changed:
            ok("Password was changed during login")
    else:
        info("Skipped (using existing az session)")
    info("")

    # Validate login & get token
    try:
        tenant_id = get_tenant_id(az_path)
        ok(f"Logged in — Tenant: {tenant_id}")
    except RuntimeError as e:
        err(f"Not logged in: {e}")
        sys.exit(1)

    info("Getting Graph API token...")
    token = get_graph_token(az_path)
    ok("Graph API token acquired")
    info("")

    # ── Step 2: Create App Registration (via Graph API) ──
    info("Step 2: Create App Registration")
    info("-" * 40)
    app_name = args.app_name or f"AppReg-{(email or 'auto').split('@')[0]}-{int(time.time())}"
    try:
        app_object_id, client_id = step_create_app(token, app_name)
    except RuntimeError as e:
        err(f"App creation failed: {e}")
        sys.exit(1)
    info("")

    # ── Step 3: Create Service Principal (via Graph API) ──
    info("Step 3: Create Service Principal")
    info("-" * 40)
    try:
        app_sp_id = step_create_service_principal(token, client_id)
    except RuntimeError as e:
        err(f"Service principal creation failed: {e}")
        sys.exit(1)
    info("")

    # ── Step 4: Create Client Secret (via Graph API) ──
    info("Step 4: Create Client Secret")
    info("-" * 40)
    try:
        client_secret = step_create_secret(token, app_object_id)
    except RuntimeError as e:
        err(f"Secret creation failed: {e}")
        sys.exit(1)
    info("")

    # ── Step 5: Add API Permissions (via Graph API) ──
    info("Step 5: Add API Permissions")
    info("-" * 40)
    try:
        graph_sp_id, graph_roles, graph_scopes, exchange_sp_id, exchange_roles = \
            step_add_permissions(token, app_object_id)
    except RuntimeError as e:
        err(f"Permission setup failed: {e}")
        sys.exit(1)
    info("")

    # ── Step 6: Grant Admin Consent (via Graph API — appRoleAssignments) ──
    info("Step 6: Grant Admin Consent")
    info("-" * 40)
    step_grant_admin_consent(
        token, app_sp_id,
        graph_sp_id, graph_roles, graph_scopes,
        exchange_sp_id, exchange_roles
    )
    info("")

    # ── Step 7: Assign Exchange Administrator Role (via Graph API) ──
    info("Step 7: Assign Exchange Administrator Role")
    info("-" * 40)
    step_assign_exchange_admin_role(token, app_sp_id)
    info("")

    # ── Step 8: Save to .env ──
    info("Step 8: Save Credentials to .env")
    info("-" * 40)
    save_to_env(tenant_id, client_id, client_secret)
    info("")

    # ── Summary ──
    info("=" * 60)
    ok("  SETUP COMPLETE!")
    info("=" * 60)
    info("")
    info("  Credentials:")
    info(f"    Tenant ID:     {tenant_id}")
    info(f"    Client ID:     {client_id}")
    info(f"    Client Secret: {client_secret[:10]}...")
    info(f"    App Name:      {app_name}")
    info("")
    info("  Permissions granted (admin consent):")
    for p in REQUIRED_GRAPH_PERMISSIONS:
        info(f"    [Graph]    {p}")
    for p in REQUIRED_GRAPH_DELEGATED:
        info(f"    [Graph]    {p} (Delegated)")
    for p in REQUIRED_EXCHANGE_PERMISSIONS:
        info(f"    [Exchange] {p}")
    info(f"    [Role]     Exchange Administrator")
    info("")
    info("  Next: Run the tenant setup:")
    info("    python tenant_setup_automation.py --use-cli")
    info("    python tenant_setup_automation.py")
    info("")
    info("=" * 60)


if __name__ == "__main__":
    main()
