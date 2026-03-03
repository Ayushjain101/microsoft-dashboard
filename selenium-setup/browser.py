"""Selenium browser for the device-code login flow."""

import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import DEFAULT_WAIT_TIMEOUT


class Browser:
    """Context-managed Chrome browser for Microsoft device-code login."""

    def __init__(self):
        options = ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, DEFAULT_WAIT_TIMEOUT)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.driver.quit()

    # ── Finders ────────────────────────────────────────────────────

    def wait_and_find(self, by, value, timeout=None):
        t = timeout or DEFAULT_WAIT_TIMEOUT
        return WebDriverWait(self.driver, t).until(
            EC.visibility_of_element_located((by, value))
        )

    def try_find(self, by, value, timeout=3):
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located((by, value))
            )
        except Exception:
            return None

    def check_for_error(self):
        for sel in [
            "#usernameError", "#passwordError", ".alert-error", "#errorText",
            "#error", ".ms-error", "#passwordError", ".error-message",
            "[role='alert']",
        ]:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    if el.is_displayed() and el.text.strip():
                        return el.text.strip()
            except Exception:
                pass
        return None
