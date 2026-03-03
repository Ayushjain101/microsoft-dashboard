#!/usr/bin/env python3
"""
delete_authenticator.py - Delete authenticator app from Microsoft Security Info
================================================================================
Logs in to https://mysignins.microsoft.com/security-info and deletes
the authenticator app registration.

Usage:
  python delete_authenticator.py --email admin@domain.com --password "Pass123!"
  python delete_authenticator.py --email admin@domain.com --password "Pass123!" --mfa-secret "ABCDEF..."
"""

import os
import sys
import time
import argparse
from datetime import datetime

# Auto-install
def ensure_packages():
    required = {"selenium": "selenium", "pyotp": "pyotp"}
    for pkg, pip_name in required.items():
        try:
            __import__(pkg)
        except ImportError:
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name, "-q"])

ensure_packages()

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pyotp


def log(level, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {level:5s}  {msg}", flush=True)

def info(msg):  log("INFO", msg)
def ok(msg):    log(" OK ", msg)
def warn(msg):  log("WARN", msg)
def err(msg):   log("ERROR", msg)


def wait_for(driver, by, value, timeout=15):
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, value))
    )

def try_find(driver, by, value, timeout=5):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )
    except Exception:
        return None

def try_click(driver, by, value, timeout=5):
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
    element.click()
    time.sleep(0.2)
    element.clear()
    time.sleep(0.1)
    element.send_keys(text)

def get_page_text(driver):
    try:
        return driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        return ""

def generate_otp(secret_key):
    try:
        secret = secret_key.replace(" ", "").upper()
        totp = pyotp.TOTP(secret)
        remaining = totp.interval - (int(time.time()) % totp.interval)
        if remaining < 5:
            info(f"  OTP expires in {remaining}s, waiting...")
            time.sleep(remaining + 1)
        code = totp.now()
        ok(f"  OTP: {code}")
        return code
    except Exception as e:
        err(f"OTP failed: {e}")
        return None


def delete_authenticator(email, password, mfa_secret=None):
    """Login to mysignins.microsoft.com and delete authenticator app."""
    info("Launching Chrome (headless)...")

    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(options=options)

    try:
        # ===== Step 1: Go to security info page =====
        info("[1] Opening security info page...")
        driver.get("https://mysignins.microsoft.com/security-info")
        time.sleep(5)

        # ===== Step 2: Enter email =====
        info("[2] Entering email...")
        email_input = wait_for(driver, By.NAME, "loginfmt", timeout=20)
        time.sleep(1)
        safe_type(email_input, email)
        info(f"  Email: {email}")
        time.sleep(1)
        try_click(driver, By.ID, "idSIButton9", timeout=5)
        time.sleep(5)

        # ===== Step 3: Enter password =====
        info("[3] Entering password...")
        pwd_input = wait_for(driver, By.NAME, "passwd", timeout=20)
        time.sleep(1)
        safe_type(pwd_input, password)
        info("  Password entered")
        time.sleep(1)
        try_click(driver, By.ID, "idSIButton9", timeout=5)
        time.sleep(6)

        # ===== Step 4: Handle MFA if prompted =====
        page_text = get_page_text(driver)
        url = driver.current_url
        info(f"  After password URL: {url}")
        info(f"  Page text: {page_text[:150]}")

        mfa_keywords = ["enter the code", "enter code", "verify your identity",
                        "authenticator", "verification code", "6-digit",
                        "approve sign-in", "approve a request"]

        if mfa_secret and any(kw in page_text for kw in mfa_keywords):
            info("[4] MFA prompted - entering OTP...")
            otp_code = generate_otp(mfa_secret)
            if otp_code:
                # Find OTP input
                otp_field = None
                for sel in ["input#idTxtBx_SAOTCC_OTC", "input[name='otc']",
                           "input[aria-label*='code']", "input[aria-label*='Code']",
                           "input[type='tel']", "input[type='number']"]:
                    otp_field = try_find(driver, By.CSS_SELECTOR, sel, timeout=3)
                    if otp_field:
                        break

                if otp_field:
                    safe_type(otp_field, otp_code)
                    time.sleep(1)
                    # Click verify
                    if not try_click(driver, By.ID, "idSubmit_SAOTCC_Continue", timeout=3):
                        try_click(driver, By.ID, "idSIButton9", timeout=3)
                    ok("  OTP submitted")
                    time.sleep(5)
                else:
                    warn("  Could not find OTP input field")
        elif any(kw in page_text for kw in mfa_keywords):
            warn("[4] MFA prompted but no secret key - cannot proceed")
            # Take screenshot
            driver.save_screenshot(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mfa_prompt.png"))
        else:
            info("[4] No MFA prompt - continuing")

        # ===== Step 5: Handle post-login pages =====
        for click_round in range(5):
            time.sleep(3)
            page_text = get_page_text(driver)
            url = driver.current_url

            # Check if we reached security info
            if "security-info" in url or "security info" in page_text:
                ok("[5] Security info page reached!")
                break

            # "Stay signed in?" -> click Yes
            if "stay signed in" in page_text:
                try_click(driver, By.ID, "idSIButton9", timeout=3)
                info(f"  Click {click_round+1}: Stay signed in -> Yes")
                continue

            # "Are you trying to sign in?" -> click Continue
            if "are you trying to sign in" in page_text:
                try_click(driver, By.ID, "idSIButton9", timeout=3)
                info(f"  Click {click_round+1}: Continue")
                continue

            # Any Next/Yes button
            if try_click(driver, By.ID, "idSIButton9", timeout=2):
                info(f"  Click {click_round+1}: Next/Yes")
                continue

            # "More information required" / MFA setup page -> click Next
            if try_click(driver, By.ID, "idSubmit_ProofUp_Redirect", timeout=2):
                info(f"  Click {click_round+1}: ProofUp redirect")
                continue

            info(f"  Click {click_round+1}: no action needed")

        # ===== Step 6: Navigate to security info =====
        info("[6] Navigating to security info page...")
        url = driver.current_url
        if "security-info" not in url:
            driver.get("https://mysignins.microsoft.com/security-info")
            time.sleep(8)

        url = driver.current_url
        info(f"  Current URL: {url}")
        time.sleep(3)

        # Check if we're on the security info page
        page_text = get_page_text(driver)
        url = driver.current_url
        info(f"  Current URL: {url}")

        if "security-info" not in url and "security" not in page_text:
            info("  Not on security info yet, navigating directly...")
            driver.get("https://mysignins.microsoft.com/security-info")
            time.sleep(5)

        # ===== Step 7: Find and delete authenticator =====
        info("[7] Looking for authenticator app to delete...")
        page_text = get_page_text(driver)

        deleted = False

        # Try multiple approaches to find and click Delete
        for attempt in range(5):
            # Approach 1: Find "Delete" buttons/links near "Authenticator"
            try:
                # Look for all delete buttons/links on the page
                delete_elements = driver.find_elements(By.XPATH,
                    "//*[contains(text(),'Delete') or contains(text(),'delete') or contains(text(),'Remove') or contains(text(),'remove')]"
                )
                for el in delete_elements:
                    el_text = el.text.strip().lower()
                    if el_text in ["delete", "remove"] and el.is_displayed():
                        info(f"  Found delete button: '{el.text}'")
                        driver.execute_script("arguments[0].click();", el)
                        time.sleep(2)

                        # Confirm deletion dialog
                        page_text = get_page_text(driver)
                        if "are you sure" in page_text or "confirm" in page_text or "yes" in page_text:
                            # Click Yes/OK/Confirm in dialog
                            for confirm_text in ["Yes", "OK", "Confirm", "Delete", "Remove"]:
                                try:
                                    confirm_btns = driver.find_elements(By.XPATH,
                                        f"//button[contains(text(),'{confirm_text}')] | //input[@value='{confirm_text}']"
                                    )
                                    for btn in confirm_btns:
                                        if btn.is_displayed():
                                            driver.execute_script("arguments[0].click();", btn)
                                            ok(f"  Confirmed deletion with '{confirm_text}'")
                                            deleted = True
                                            break
                                except Exception:
                                    pass
                                if deleted:
                                    break

                        if not deleted:
                            # Maybe it was deleted without confirmation
                            time.sleep(2)
                            new_page_text = get_page_text(driver)
                            if "authenticator" not in new_page_text:
                                deleted = True
                                ok("  Authenticator deleted!")
                            elif "deleted" in new_page_text or "removed" in new_page_text:
                                deleted = True
                                ok("  Authenticator deleted!")

                        if deleted:
                            break
            except Exception as e:
                info(f"  Attempt {attempt+1} error: {e}")

            if deleted:
                break

            # Approach 2: Try clicking via aria-label or data attributes
            try:
                del_btns = driver.find_elements(By.CSS_SELECTOR,
                    "button[aria-label*='Delete'], button[aria-label*='delete'], "
                    "button[aria-label*='Remove'], a[aria-label*='Delete'], "
                    "[data-testid*='delete'], [data-testid*='Delete']"
                )
                for btn in del_btns:
                    if btn.is_displayed():
                        label = btn.get_attribute("aria-label") or btn.text
                        if "authenticator" in label.lower() or "delete" in label.lower():
                            info(f"  Clicking: {label}")
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(3)

                            # Confirm
                            for confirm_sel in ["button.ms-Button--primary", "button[aria-label*='Yes']",
                                               "button[aria-label*='Confirm']", "button[aria-label*='Delete']"]:
                                if try_click(driver, By.CSS_SELECTOR, confirm_sel, timeout=2):
                                    ok("  Deletion confirmed")
                                    deleted = True
                                    break
                            if deleted:
                                break
            except Exception:
                pass

            if deleted:
                break

            info(f"  Attempt {attempt+1}: retrying...")
            time.sleep(2)

        # Take screenshot for debugging
        ss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "security_info.png")
        driver.save_screenshot(ss_path)

        if deleted:
            ok("=== Authenticator app DELETED from security info ===")
        else:
            # Check if there's no authenticator to delete
            page_text = get_page_text(driver)
            if "authenticator" not in page_text:
                ok("=== No authenticator found on security info page ===")
            else:
                warn("=== Could not delete authenticator - check security_info.png ===")
                info(f"  Page text snippet: {page_text[:300]}")

        time.sleep(2)
        return deleted

    except Exception as e:
        err(f"Error: {e}")
        try:
            ss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "delete_error.png")
            driver.save_screenshot(ss_path)
            info(f"  Screenshot: {ss_path}")
        except Exception:
            pass
        raise
    finally:
        driver.quit()
        info("Chrome closed")


def main():
    parser = argparse.ArgumentParser(description="Delete authenticator from Microsoft Security Info")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--password", required=True, help="User password")
    parser.add_argument("--mfa-secret", default=None, help="MFA secret key for OTP generation")
    args = parser.parse_args()

    result = delete_authenticator(args.email, args.password, args.mfa_secret)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
