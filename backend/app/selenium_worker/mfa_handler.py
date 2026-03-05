"""Device-code login flow with MFA handling via Selenium.

Uses `az login --use-device-code` + Chrome browser automation.
Handles: email, password, forced password change, MFA enrollment/prompt.

Adapted from selenium-setup/mfa_handler.py — removed print statements,
uses logging instead, otherwise functionally identical.
"""

import json
import logging
import os
import re
import subprocess
import threading
import time

from selenium.webdriver.common.by import By

from app.selenium_worker.browser import Browser

logger = logging.getLogger(__name__)


# ── Azure CLI helpers ──────────────────────────────────────────────────────────

def find_az() -> str:
    for cmd in ["which az", "where az"]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0]
        except Exception:
            pass
    raise RuntimeError("Azure CLI (az) not found!")


def az_command(az_path: str, args: list) -> str:
    cmd = [az_path] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "az command failed")
    return result.stdout.strip()


def get_graph_token(az_path: str) -> str:
    raw = az_command(az_path, [
        "account", "get-access-token",
        "--scope", "https://graph.microsoft.com/.default", "-o", "json",
    ])
    return json.loads(raw)["accessToken"]


def get_tenant_id(az_path: str) -> str:
    raw = az_command(az_path, ["account", "show", "-o", "json"])
    return json.loads(raw)["tenantId"]


def get_exchange_token(az_path: str) -> str:
    raw = az_command(az_path, [
        "account", "get-access-token",
        "--resource", "https://outlook.office365.com", "-o", "json",
    ])
    return json.loads(raw)["accessToken"]


# ── Device Code Login ──────────────────────────────────────────────────────────

def do_az_login(az_path: str, email: str, password: str, new_password: str = None, mfa_secret: str = None) -> dict:
    logger.info("Starting az login with device code ...")
    full_cmd = f'"{az_path}" login --use-device-code --allow-no-subscriptions'
    proc = subprocess.Popen(
        full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True,
    )

    output_lines = []

    def read_output(pipe, lines):
        for line in iter(pipe.readline, ""):
            lines.append(line)
            logger.debug(f"az: {line.strip()}")

    stderr_thread = threading.Thread(target=read_output, args=(proc.stderr, output_lines))
    stderr_thread.daemon = True
    stderr_thread.start()

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

    logger.info(f"Got device code: {device_code}")
    login_result = _browser_login(email, password, new_password, device_code, mfa_secret=mfa_secret)

    logger.info("Waiting for az login to complete ...")
    try:
        exit_code = proc.wait(timeout=300)
        if exit_code == 0:
            logger.info("Azure CLI login successful")
        else:
            logger.warning(f"az login exited with code {exit_code}")
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.warning("az login timed out")

    return login_result


def _browser_login(email: str, password: str, new_password: str, device_code: str, mfa_secret: str = None) -> dict:
    logger.info("Launching Chrome for device code login ...")
    result = {"password_changed": False, "working_password": password}

    with Browser() as b:
        driver = b.driver

        # Device login page (with retry for rate-limiting)
        code_input = None
        for page_attempt in range(5):
            if page_attempt > 0:
                wait_time = 15 * page_attempt
                logger.warning(f"Device login page not ready, retrying in {wait_time}s (attempt {page_attempt + 1}/5)...")
                time.sleep(wait_time)
            driver.get("https://login.microsoftonline.com/common/oauth2/deviceauth")
            time.sleep(3)
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                if "high demand" in body_text or "please wait" in body_text or "try again later" in body_text:
                    logger.warning("Microsoft rate-limiting detected — will retry")
                    continue
            except Exception:
                pass
            code_input = b.try_find(By.ID, "otc", timeout=15)
            if code_input:
                break
        if not code_input:
            raise RuntimeError("Could not load device login page after 5 attempts")

        logger.info(f"Entering device code: {device_code}")
        time.sleep(0.5)
        code_input.send_keys(device_code)
        driver.find_element(By.ID, "idSIButton9").click()
        logger.info("Device code submitted")

        # Email
        time.sleep(2)
        email_input = b.wait_and_find(By.NAME, "loginfmt")
        time.sleep(0.5)
        email_input.clear()
        email_input.send_keys(email)
        logger.info(f"Email entered: {email}")
        time.sleep(0.5)
        b.wait_and_find(By.ID, "idSIButton9").click()

        time.sleep(2)
        error = b.check_for_error()
        if error:
            raise RuntimeError(f"Email error: {error}")

        # Password
        time.sleep(2)
        pwd_input = b.wait_and_find(By.NAME, "passwd")
        time.sleep(0.5)
        pwd_input.click()
        pwd_input.clear()
        pwd_input.send_keys(password)
        logger.info("Password entered")
        time.sleep(0.5)
        b.wait_and_find(By.ID, "idSIButton9").click()

        time.sleep(3)
        error = b.check_for_error()
        if error:
            raise RuntimeError(f"Login error: {error}")

        # Password change detection
        password_change_keywords = [
            "update your password", "change your password",
            "password has expired", "must change your password",
            "you need to update", "enter new password",
            "confirm new password", "create new password",
            "new password", "reset your password",
        ]
        password_change_detected = False
        for _ in range(8):
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                visible_pwd_fields = [
                    el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                    if el.is_displayed()
                ]
                if any(kw in page_text for kw in password_change_keywords):
                    password_change_detected = True
                    break
                if len(visible_pwd_fields) >= 2:
                    password_change_detected = True
                    break
                current_url = driver.current_url.lower()
                if any(kw in current_url for kw in ["kmsi", "mysignins", "proofup", "mfasetup", "appconfirm"]):
                    break
            except Exception:
                pass
            time.sleep(1)

        if password_change_detected:
            logger.info("PASSWORD CHANGE required!")
            if not new_password:
                raise RuntimeError("Password change required but no new_password provided")
            actual_new = _handle_password_change(b, password, new_password)
            result["password_changed"] = True
            result["working_password"] = actual_new

        # MFA detection
        mfa_keywords = [
            "verify your identity", "more information required",
            "prove you", "authenticator", "approve a request",
            "enter code", "verification code", "keep your account secure",
            "set up another way", "action required", "security defaults",
            "multifactor authentication", "install microsoft authenticator",
            "set up a different", "authentication app",
        ]
        mfa_url_keywords = ["mysignins.microsoft.com/register", "proofup", "mfasetup"]
        mfa_detected = False
        for _ in range(8):
            time.sleep(1)
            current_url = driver.current_url.lower()
            if any(kw in current_url for kw in mfa_url_keywords):
                mfa_detected = True
                break
            try:
                page_snippet = driver.find_element(By.TAG_NAME, "body").text.lower()
                if any(kw in page_snippet for kw in mfa_keywords):
                    mfa_detected = True
                    break
            except Exception:
                pass

        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        current_url = driver.current_url.lower()
        if (mfa_detected or
                any(kw in page_text for kw in mfa_keywords) or
                any(kw in current_url for kw in mfa_url_keywords)):
            if mfa_secret:
                # We have a stored MFA secret — use it to answer the OTP prompt
                logger.info("MFA detected with stored secret — answering OTP prompt directly")
                _handle_mfa_with_known_secret(b, mfa_secret)
                result["mfa_secret"] = mfa_secret
            else:
                # No stored secret — go through enrollment flow
                new_mfa_secret = _handle_mfa(b)
                if new_mfa_secret:
                    result["mfa_secret"] = new_mfa_secret

        # Device code app confirmation
        for confirm_round in range(8):
            time.sleep(3)
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                break
            page_lower = page_text.lower()
            if "signed in" in page_lower or "successfully" in page_lower or "you may now close" in page_lower:
                logger.info("Login confirmed in browser!")
                break
            clicked = False
            button_selectors = [
                (By.ID, "idSIButton9"), (By.ID, "idBtn_Accept"),
                (By.CSS_SELECTOR, "button.button_primary"),
                (By.XPATH, "//button[contains(text(),'Continue')]"),
                (By.XPATH, "//button[contains(text(),'Yes')]"),
                (By.XPATH, "//button[contains(text(),'Accept')]"),
                (By.XPATH, "//button[contains(text(),'No')]"),
                (By.XPATH, "//input[@value='Continue']"),
                (By.XPATH, "//input[@value='Yes']"),
                (By.XPATH, "//a[contains(text(),'Continue')]"),
                (By.CSS_SELECTOR, "input[type='submit']"),
            ]
            for sel_by, sel_val in button_selectors:
                try:
                    btn = driver.find_element(sel_by, sel_val)
                    if btn.is_displayed():
                        label = btn.text or btn.get_attribute("value") or "button"
                        btn.click()
                        logger.info(f"Clicked '{label}' (round {confirm_round + 1})")
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                time.sleep(5)

    logger.info("Browser login flow completed")
    return result


def _handle_password_change(b, old_password: str, new_password: str) -> str:
    from selenium.webdriver.common.keys import Keys
    driver = b.driver
    candidate = new_password

    password_change_page_keywords = [
        "update your password", "change your password",
        "password has expired", "must change your password",
        "enter new password", "confirm new password",
        "create new password", "new password",
    ]

    suffixes = ["", "1", "!", "1!", "#1"]
    for attempt, suffix in enumerate(suffixes):
        if attempt > 0:
            candidate = new_password + suffix
            logger.warning(f"Retrying password change with modified password (attempt {attempt + 1})")

        time.sleep(2)
        all_inputs = []
        for _ in range(5):
            all_inputs = [
                el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                if el.is_displayed()
            ]
            if len(all_inputs) >= 2:
                break
            time.sleep(1)

        if len(all_inputs) >= 3:
            _safe_fill(all_inputs[0], old_password)
            time.sleep(0.3)
            _safe_fill(all_inputs[1], candidate)
            time.sleep(0.3)
            _safe_fill(all_inputs[2], candidate)
        elif len(all_inputs) == 2:
            _safe_fill(all_inputs[0], candidate)
            time.sleep(0.3)
            _safe_fill(all_inputs[1], candidate)
        elif len(all_inputs) == 1:
            _safe_fill(all_inputs[0], old_password)
            time.sleep(0.5)
            _click_submit(driver)
            time.sleep(3)
            all_inputs = [
                el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                if el.is_displayed()
            ]
            if len(all_inputs) >= 2:
                _safe_fill(all_inputs[0], candidate)
                time.sleep(0.3)
                _safe_fill(all_inputs[1], candidate)
            elif len(all_inputs) == 1:
                _safe_fill(all_inputs[0], candidate)
            else:
                continue
        else:
            if attempt < len(suffixes) - 1:
                time.sleep(2)
                continue
            raise RuntimeError(f"Expected 2-3 password fields, found {len(all_inputs)}")

        time.sleep(0.5)
        _click_submit(driver)

        still_on_pwd_page = True
        error = None
        for _ in range(12):
            time.sleep(1)
            error = b.check_for_error()
            if error:
                error_lower = error.lower()
                retryable = any(kw in error_lower for kw in [
                    "same", "incorrect", "previously used", "recent",
                    "complexity", "too short", "minimum", "requirements",
                ])
                if retryable and attempt < len(suffixes) - 1:
                    break
                if retryable:
                    break
                raise RuntimeError(f"Password change error: {error}")
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                visible_pwd_fields = [
                    el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                    if el.is_displayed()
                ]
            except Exception:
                still_on_pwd_page = False
                break
            on_change_page = (
                any(kw in page_text for kw in password_change_page_keywords)
                and len(visible_pwd_fields) >= 2
            )
            if not on_change_page:
                still_on_pwd_page = False
                break

        if error and attempt < len(suffixes) - 1:
            continue
        if still_on_pwd_page:
            if attempt < len(suffixes) - 1:
                continue
            raise RuntimeError("Password change did not go through")

        logger.info("Password changed successfully!")
        return candidate

    raise RuntimeError("Password change failed after all attempts")


def _safe_fill(element, text):
    try:
        element.click()
        time.sleep(0.1)
        element.clear()
        time.sleep(0.1)
        element.send_keys(text)
    except Exception:
        time.sleep(0.5)
        element.clear()
        element.send_keys(text)


def _click_submit(driver):
    submit_selectors = [
        (By.ID, "idSIButton9"),
        (By.CSS_SELECTOR, "input[type='submit']"),
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.CSS_SELECTOR, "button.button_primary"),
        (By.CSS_SELECTOR, "[data-report-event='Signin_Submit']"),
        (By.XPATH, "//button[contains(text(),'Sign in')]"),
        (By.XPATH, "//button[contains(text(),'Submit')]"),
        (By.XPATH, "//button[contains(text(),'Update')]"),
        (By.XPATH, "//input[@value='Sign in']"),
        (By.XPATH, "//input[@value='Submit']"),
    ]
    for sel_by, sel_val in submit_selectors:
        try:
            btn = driver.find_element(sel_by, sel_val)
            if btn.is_displayed():
                btn.click()
                return True
        except Exception:
            continue
    try:
        from selenium.webdriver.common.keys import Keys
        pwd_fields = [
            el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            if el.is_displayed()
        ]
        if pwd_fields:
            pwd_fields[-1].send_keys(Keys.RETURN)
            return True
    except Exception:
        pass
    return False


def _handle_mfa_with_known_secret(b, mfa_secret: str):
    """Handle MFA OTP prompt using a previously stored TOTP secret."""
    driver = b.driver
    logger.info("Handling MFA with known secret — looking for OTP input")

    # Wait for OTP input field to appear (may need to click through pages first)
    otp_field = None
    for attempt in range(15):
        otp_field = _mfa_find_otp_input(driver)
        if otp_field:
            break
        # Try clicking through intermediate pages (e.g. "Verify your identity")
        for btn_id in ["idSubmit_ProofUp_Redirect", "idSIButton9"]:
            if _mfa_try_click(driver, By.ID, btn_id, timeout=2):
                time.sleep(3)
                break
        # Check for "I can't use my Microsoft Authenticator app right now" or similar
        # to switch to TOTP code entry
        try:
            for link in driver.find_elements(By.CSS_SELECTOR, "a, button, [role='button']"):
                link_text = (link.text or "").lower()
                if link.is_displayed() and any(kw in link_text for kw in [
                    "different method", "another way", "can't use",
                    "use a verification code", "authenticator app",
                    "enter code", "use code",
                ]):
                    driver.execute_script("arguments[0].click();", link)
                    logger.info(f"Clicked '{link.text}' to switch to code entry")
                    time.sleep(3)
                    break
        except Exception:
            pass
        time.sleep(2)

    if not otp_field:
        otp_field = _mfa_find_otp_input(driver)

    if otp_field:
        otp_code = _mfa_generate_otp(mfa_secret)
        if not otp_code:
            logger.error("Failed to generate OTP from stored secret")
            return
        otp_field.click()
        time.sleep(0.2)
        otp_field.clear()
        time.sleep(0.1)
        otp_field.send_keys(otp_code)
        time.sleep(0.5)

        if not _mfa_try_click(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3):
            _mfa_click_next(driver)
        time.sleep(4)

        # Click through any remaining confirmation pages
        for _ in range(5):
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                if "signed in" in page_text or "successfully" in page_text:
                    break
            except Exception:
                break
            for btn_id in ["idSIButton9", "idBtn_Accept"]:
                if _mfa_try_click(driver, By.ID, btn_id, timeout=2):
                    time.sleep(3)
                    break
            else:
                time.sleep(2)
        logger.info("MFA verification with known secret completed")
    else:
        logger.error("Could not find OTP input field for known-secret MFA")


def _handle_mfa(b):
    """Handle MFA enrollment — extract TOTP secret, generate OTP, verify."""
    import pyotp
    driver = b.driver
    logger.info("MFA ENROLLMENT DETECTED — starting automated setup")

    saved_secret_key = None

    # Step A: Click through Action Required pages
    for _ in range(3):
        time.sleep(2)
        if _mfa_try_click(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=3):
            time.sleep(3)
            continue
        if _mfa_try_click(driver, By.ID, "idSIButton9", timeout=3):
            time.sleep(3)
            continue
        break

    # Step B: Click "Set up a different authentication app"
    diff_app_clicked = False
    for attempt in range(5):
        for link_kw in ["different authentication app", "different authenticator app",
                        "I want to use a different"]:
            try:
                links = driver.find_elements(By.PARTIAL_LINK_TEXT, link_kw)
                for link in links:
                    if link.is_displayed():
                        driver.execute_script("arguments[0].click();", link)
                        diff_app_clicked = True
                        break
            except Exception:
                pass
            if diff_app_clicked:
                break
        if not diff_app_clicked:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, "a"):
                    el_text = (el.text or "").lower()
                    if len(el_text) < 100 and "different" in el_text and el.is_displayed():
                        driver.execute_script("arguments[0].click();", el)
                        diff_app_clicked = True
                        break
            except Exception:
                pass
        if not diff_app_clicked:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, "button, [role='button'], [role='link']"):
                    el_text = (el.text or "").lower()
                    if len(el_text) < 100 and "different" in el_text and el.is_displayed():
                        driver.execute_script("arguments[0].click();", el)
                        diff_app_clicked = True
                        break
            except Exception:
                pass
        if diff_app_clicked:
            break
        time.sleep(3)

    if not diff_app_clicked:
        _mfa_click_next(driver)
    time.sleep(4)

    # Step C: Click Next to QR code page
    if _mfa_try_click(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=5):
        pass
    else:
        _mfa_click_next(driver)
    time.sleep(4)

    # Step D: Click "Can't scan the QR code?"
    cant_scan_clicked = False
    for attempt in range(5):
        try:
            btn = driver.find_element(By.CSS_SELECTOR,
                'button[data-testid="activation-qr-show/hide-info-button"]')
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                cant_scan_clicked = True
        except Exception:
            pass
        if not cant_scan_clicked:
            cant_scan_clicked = _mfa_click_cant_scan(driver)
        if cant_scan_clicked:
            break
        time.sleep(2)
    time.sleep(3)

    # Step E: Extract secret key
    saved_secret_key = _mfa_extract_secret(driver)
    if not saved_secret_key:
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
        logger.info(f"SECRET KEY: {saved_secret_key[:8]}...{saved_secret_key[-4:]}")

        otp_code = _mfa_generate_otp(saved_secret_key)
        if not otp_code:
            logger.error("Failed to generate OTP — invalid secret key, skipping MFA enrollment")
            return None
        _mfa_click_next(driver)
        time.sleep(4)

        # Step G: Find OTP input and enter code
        otp_field = _mfa_find_otp_input(driver)
        if not otp_field:
            for _ in range(10):
                time.sleep(2)
                otp_field = _mfa_find_otp_input(driver)
                if otp_field:
                    break
                if _mfa_try_click(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=1):
                    time.sleep(3)
                elif _mfa_try_click(driver, By.ID, "idSIButton9", timeout=1):
                    time.sleep(3)

        if otp_field:
            otp_code = _mfa_generate_otp(saved_secret_key)
            if not otp_code:
                logger.error("Failed to generate OTP on retry")
                return None
            otp_field.click()
            time.sleep(0.2)
            otp_field.clear()
            time.sleep(0.1)
            otp_field.send_keys(otp_code)
            time.sleep(0.5)

            if not _mfa_try_click(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3):
                _mfa_click_next(driver)
            time.sleep(4)

            # Retry if OTP was rejected
            try:
                error_el = driver.find_element(By.CSS_SELECTOR, "[role='alert'], .error-text, #errorText")
                if error_el.is_displayed() and error_el.text.strip():
                    otp_code = _mfa_generate_otp(saved_secret_key)
                    otp_field = _mfa_find_otp_input(driver)
                    if otp_field and otp_code:
                        otp_field.click()
                        otp_field.clear()
                        otp_field.send_keys(otp_code)
                        time.sleep(0.5)
                        if not _mfa_try_click(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3):
                            _mfa_click_next(driver)
                        time.sleep(4)
            except Exception:
                pass

            # Step H: Click Done
            time.sleep(3)
            for _ in range(5):
                for btn_id in ["idSIButton9", "idSubmit_ProofUp_Redirect"]:
                    if _mfa_try_click(driver, By.ID, btn_id, timeout=2):
                        time.sleep(3)
                        break
                else:
                    try:
                        for btn in driver.find_elements(By.CSS_SELECTOR,
                                "button, input[type='submit'], input[type='button']"):
                            btn_text = (btn.text or btn.get_attribute("value") or "").lower()
                            if btn.is_displayed() and any(kw in btn_text
                                    for kw in ["done", "finish", "complete", "ok", "got it"]):
                                driver.execute_script("arguments[0].click();", btn)
                                time.sleep(3)
                                break
                    except Exception:
                        pass
                    time.sleep(2)
                    continue
                break
    else:
        logger.warning("No secret key found — waiting for manual MFA completion (120s)...")
        for _ in range(60):
            time.sleep(2)
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                url = driver.current_url
                if any(kw in page_text for kw in ["stay signed in", "you have signed in",
                        "are you trying to sign in", "successfully"]):
                    break
                if "kmsi" in url or "appconfirm" in url:
                    break
            except Exception:
                pass

    return saved_secret_key


def _mfa_try_click(driver, by, value, timeout=5):
    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))
        if el and el.is_displayed():
            try:
                el.click()
            except Exception:
                driver.execute_script("arguments[0].click();", el)
            return True
    except Exception:
        pass
    return False


def _mfa_click_next(driver, timeout=10):
    for btn_id in ["idSubmit_ProofUp_Redirect", "idSIButton9",
                    "idSubmit_SAOTCC_Continue", "idBtn_Back"]:
        if _mfa_try_click(driver, By.ID, btn_id, timeout=3):
            return True
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


def _mfa_click_cant_scan(driver):
    link_texts = ["can't scan", "cant scan", "can not scan", "enter code manually",
                  "manual entry", "enter manually", "configure without",
                  "without scanning", "can't use", "i want to set up a different method"]
    for text in link_texts:
        try:
            links = driver.find_elements(By.PARTIAL_LINK_TEXT, text)
            for link in links:
                if link.is_displayed():
                    link.click()
                    time.sleep(2)
                    return True
        except Exception:
            pass
    try:
        for link in driver.find_elements(By.TAG_NAME, "a"):
            link_text = link.text.lower()
            if any(kw in link_text for kw in link_texts) and link.is_displayed():
                link.click()
                time.sleep(2)
                return True
    except Exception:
        pass
    try:
        for btn in driver.find_elements(By.TAG_NAME, "button"):
            btn_text = btn.text.lower()
            if any(kw in btn_text for kw in link_texts) and btn.is_displayed():
                btn.click()
                time.sleep(2)
                return True
    except Exception:
        pass
    try:
        for el in driver.find_elements(By.CSS_SELECTOR,
                "[role='link'], [role='button'], .link, .clickable"):
            el_text = el.text.lower()
            if any(kw in el_text for kw in link_texts) and el.is_displayed():
                el.click()
                time.sleep(2)
                return True
    except Exception:
        pass
    return False


def _mfa_extract_secret(driver):
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        # Labeled patterns (preceded by "Secret key:", "Key:", etc.) — more trustworthy
        labeled_patterns = [
            r"(?:Secret\s*(?:key)?|Key|Code)[:\s]+([A-Z2-7]{16,})",
            r"(?:secret|key)[=:\s]+([a-zA-Z2-7]{16,})",
        ]
        # Unlabeled patterns — require stricter validation (32+ chars)
        unlabeled_patterns = [
            r"\b([A-Z2-7]{32,64})\b",
        ]
        for pattern in labeled_patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                secret = match.group(1).strip().upper()
                if len(secret) >= 16 and re.match(r'^[A-Z2-7]+$', secret):
                    if _validate_totp_secret(secret):
                        return secret
                    else:
                        logger.warning(f"Rejected labeled secret match: {secret[:8]}...")
        for pattern in unlabeled_patterns:
            match = re.search(pattern, body_text)
            if match:
                secret = match.group(1).strip().upper()
                if re.match(r'^[A-Z2-7]+$', secret) and _validate_totp_secret(secret):
                    return secret
    except Exception:
        pass
    return None


def _validate_totp_secret(secret: str) -> bool:
    """Validate that a string is a real TOTP secret, not a false match like a tenant name."""
    import base64
    try:
        padded = secret + "=" * (-len(secret) % 8)
        decoded = base64.b32decode(padded)
        # TOTP secrets need at least 80 bits (10 bytes) per RFC 4226.
        # Microsoft uses 80-bit or 160-bit secrets depending on account type.
        if len(decoded) < 10:
            return False
        return True
    except Exception:
        return False


def _mfa_generate_otp(secret_key):
    import pyotp
    secret = secret_key.replace(" ", "").upper()
    try:
        totp = pyotp.TOTP(secret)
        remaining = totp.interval - (int(time.time()) % totp.interval)
        if remaining < 5:
            time.sleep(remaining + 1)
        return totp.now()
    except Exception as e:
        logger.error(f"Failed to generate OTP from secret {secret[:8]}...: {e}")
        return None


def _mfa_find_otp_input(driver):
    selectors = [
        "input#idTxtBx_SAOTCC_OTC", "input[name='otc']",
        "input[aria-label*='code']", "input[aria-label*='Code']",
        "input[placeholder*='code']", "input[placeholder*='Code']",
        "input[type='tel']", "input[type='number']",
        "input[aria-label*='verification']", "input[aria-label*='Verification']",
        "input[id*='otp']", "input[id*='OTP']",
        "input[id*='code']", "input[id*='Code']",
        "input[name*='otp']", "input[name*='code']",
    ]
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el and el.is_displayed():
                return el
        except Exception:
            pass
    try:
        for inp in driver.find_elements(By.CSS_SELECTOR,
                "input[type='text'], input[type='tel'], input[type='number'], input:not([type])"):
            if inp.is_displayed() and inp.is_enabled():
                maxlen = inp.get_attribute("maxlength") or ""
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                if maxlen in ("6", "8") or "code" in placeholder or "otp" in placeholder:
                    return inp
    except Exception:
        pass
    return None
