"""Quick debug script to check what the device login page looks like."""
from browser import Browser
from selenium.webdriver.common.by import By
import time

with Browser() as b:
    print("Navigating to devicelogin...")
    b.driver.get("https://microsoft.com/devicelogin")
    time.sleep(5)
    print("URL:", b.driver.current_url)
    print("Title:", b.driver.title)
    b.driver.save_screenshot("/tmp/devicelogin_debug.png")

    try:
        otc = b.driver.find_element(By.ID, "otc")
        print("otc field found! displayed:", otc.is_displayed())
    except Exception:
        print("otc field NOT found")

    inputs = b.driver.find_elements(By.TAG_NAME, "input")
    for inp in inputs:
        iid = inp.get_attribute("id")
        iname = inp.get_attribute("name")
        itype = inp.get_attribute("type")
        idisp = inp.is_displayed()
        print(f"  input: id={iid}, name={iname}, type={itype}, displayed={idisp}")

    body = b.driver.find_element(By.TAG_NAME, "body").text
    print("Body text (first 500):", body[:500])
