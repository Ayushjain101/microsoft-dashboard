from asyncio import wait
from selenium.webdriver.common.by import By
import os
import time
from selenium import webdriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
import requests
import traceback
import sys
import traceback

from helpers import getNumber, getSMS, solve_captcha

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

DEFAULT_USER_API_KEY = "AIzaSyA3bX4Zy7f1c0u6k3c1b3c1b3c1b3c1b3c1"

def MyPrintLog(*args):
    print(*args)
    with open("log.txt", "a") as f:
        print(*args, file=f)


class Instantly():
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # self.driver.close()
        self.driver.quit()

    def __init__(self, email, password, headless=True, login=True, proxyServer="http://localhost:9000") -> None:
        self.email: str = email
        self.password: str = password
        chrome_options = Options()

        chrome_options.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
        chrome_options.add_argument("--window-size=1400,800")
        # chrome_options.add_argument(
        #     "--user-data-dir=/tmp/unique_chrome_profile_123")
        
        # chrome_options.add_argument(f"--proxy-server={proxyServer}")
        
        if headless:
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument('--disable-dev-shm-usage')

        chrome_options.binary_location = "/usr/bin/google-chrome"
        webdriver_service = Service("/usr/bin/chromedriver")

        driver = webdriver.Chrome(service=webdriver_service,
                                  options=chrome_options)
        self.driver = driver
        
        if login:
            self.login()

    def login(self):
        url = "https://app.instantly.ai/auth/login"
        # print title of the page
        self.driver.get(url)
        wait = WebDriverWait(self.driver, 30)
        emailInp = wait.until(lambda driver: driver.find_element(
            By.CSS_SELECTOR, ".position-relative:nth-child(1) > .form-control"))
        # MyPrintLog(elem)
        emailInp.send_keys(self.email)
        passwordInp = self.driver.find_element(
            By.CSS_SELECTOR, ".mt-3 > .form-control")
        passwordInp.send_keys(self.password)

        loginBtn = self.driver.find_element(By.CSS_SELECTOR, "button.btn.btn-primary")
        loginBtn.click()
        time.sleep(5)
        # refresh the page
        self.driver.refresh()
        print("Logged in")
        time.sleep(5)

    def find_element_by_inner_html(self, inner_html, innerMost=False, click=False) -> WebElement:
        script1 = f'''
        var elements = document.getElementsByTagName('*');
        for (var i = 0; i < elements.length; i++) {{
            if (elements[i].innerHTML.includes("{inner_html}")) {{
                return elements[i];
            }}
        }}
        return null;
        '''
        script2 = """
        function findInnermostElementByInnerHTML(inner_html) {
            var elements = document.getElementsByTagName('*');
            var innermostElement = null;

            for (var i = 0; i < elements.length; i++) {
                if (elements[i].innerHTML.includes(inner_html)) {
                    var childElements = elements[i].getElementsByTagName('*');
                    var foundInChild = false;

                    for (var j = 0; j < childElements.length; j++) {
                        if (childElements[j].innerHTML.includes(inner_html)) {
                            foundInChild = true;
                            break;
                        }
                    }

                    if (!foundInChild) {
                        innermostElement = elements[i];
                    }
                }
            }

            return innermostElement;
        }
        return findInnermostElementByInnerHTML(arguments[0]);
        """
        if innerMost:
            element = self.driver.execute_script(script2, inner_html)
            return element
        element = self.driver.execute_script(script1)
        if click and element is not None:
            script3 = "arguments[0].click();"
            self.driver.execute_script(script3, element)
        return element
# input#\:1k
# *:nth-child(3) > * > *:nth-child(1) > *:nth-child(3) > * > * > *:nth-child(1) > *

# button[guidedhelpid="save_changes_button"]
    def enableIMAP(self, email, password, debug=False):
        self.driver.get("https://www.google.com/intl/en-US/gmail/about/")
        time.sleep(2)
        wait = WebDriverWait(self.driver, 30)

        try:
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, '.button:nth-child(2) > .button__label')).click()
        except Exception as e:
            print(e)
        time.sleep(5)
        self.signInGoogle(email, password)
        
        time.sleep(10)
        if wait.until(lambda driver: driver.current_url.startswith("https://mail.google.com/")):
            MyPrintLog("Logged in")
        else:
            MyPrintLog("Login failed")
            return False
        # return True
    
    


        # self.driver.refresh()
        # self.find_element_by_inner_html(
        #     "Get started", innerMost=True, click=True)
        # if self.find_element_by_inner_html(
        #         "Turn off smart features", innerMost=True) is not None:
        #     MyPrintLog("Turning off smart features")
        #     try:
        #         self.find_element_by_inner_html(
        #             "Turn off smart features", innerMost=True).click()
        #         self.find_element_by_inner_html(
        #             "Get started", innerMost=True, click=True)
        #         wait.until(lambda driver: driver.find_element(
        #             By.CSS_SELECTOR, "button:nth-child(1)")).click()
        #         time.sleep(5)
        #         wait.until(lambda driver: driver.find_element(
        #             By.CSS_SELECTOR, "button:nth-child(1)")).click()
        #         wait.until(lambda driver: driver.find_element(
        #             By.CSS_SELECTOR, "div.T-P-aut-UR")).click()
        #     except:
        #         self.driver.refresh()
        # else:
        #     MyPrintLog("Smart features already turned off")

        # try:
        #     wait.until(lambda driver: driver.find_element(
        #         By.CSS_SELECTOR, "div.T-P-aut-UR")).click()
        # except:
        #     MyPrintLog("No turn off button")

        self.driver.get("https://mail.google.com/mail/u/0/#settings/fwdandpop")
        # MyPrintLog("Opened settings")
        # if debug:
        #     time.sleep(500)
        # return "Debug"
        # MyPrintLog(self.driver.current_url)
        time.sleep(30)
        try:
            self.find_element_by_inner_html(
                "Continue", innerMost=True, click=True)
        except:
            MyPrintLog("No continue button")
        print("Opened settings")
        try:
            k = wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "*:nth-child(3) > * > *:nth-child(1) > *:nth-child(3) > * > * > *:nth-child(1) > *"))
            self.simClick(k)
            self.find_element_by_inner_html(
                "Enable IMAP", innerMost=True, click=True)
            f = wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, 'button[guidedhelpid="save_changes_button"]'))
            self.simClick(f)
            print("Clicked Save")
        except Exception as e:
            print(e)
            print("Error in enabling IMAP")
            return False
        # self.find_element_by_inner_html(
        #     "Enable IMAP", innerMost=True, click=True)
        # self.find_element_by_inner_html(
        #     "Save Changes", innerMost=True, click=True)
        time.sleep(10)
        for i in range(4):
            try:
                a = self.find_element_by_inner_html(
                    "IMAP is enabled", innerMost=True)
                if a is not None:
                    MyPrintLog("Enabled IMAP", email)
                    requests.get(
                        "https://n8n.icedautomation.com/webhook/imapdone?email=" + email)
                    return True
                else:
                    raise Exception("IMAP not enabled status not found")
            except:
                self.driver.get(
                    "https://mail.google.com/mail/u/0/#settings/fwdandpop")
                MyPrintLog("Status not found retrying")
                self.find_element_by_inner_html(
                    "Enable IMAP", innerMost=True, click=True)
                self.find_element_by_inner_html(
                    "Save Changes", innerMost=True, click=True)
                time.sleep(5)

        MyPrintLog("Failed to enable IMAP: ", email)
        self.driver.save_screenshot("errorpng/imap.png")
        return False

    def simClick(self, element):
        script = "arguments[0].click();"
        self.driver.execute_script(script, element)

    def addGmailAccount(self, email, password, orgName):
        if self.driver.current_url != "https://app.instantly.ai/app/accounts":
            self.driver.get("https://app.instantly.ai/app/accounts")
        time.sleep(5)
        wait = WebDriverWait(self.driver, 30)

        if self.email.lower() == "arnav@icedautomations.com" or self.email.lower() == "abhishek@icedautomations.com":
            # temp
            # wait.until(lambda driver: driver.find_element(
                # By.CSS_SELECTOR, "div:nth-child(2) > div:nth-child(1) > div > div > button:nth-child(1)")).click()
            wait.until(lambda driver: driver.find_element(By.XPATH, "//button[.//span[contains(text(), 'Icedautomations')]]")).click()
            time.sleep(5)
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "div > li:nth-child(13)")).click()

        if orgName is not None and orgName != "":
            # MyPrintLog("Adding account for ", orgName)
            a = wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.cursorPointer"))
            self.simClick(a)
            # time.sleep(4)
            # c = self.driver.find_element(By.CSS_SELECTOR, "div > li:nth-child(2)")
            # self.simClick(c)
            b = self.find_element_by_inner_html(
                orgName, innerMost=True, click=True)
            if b == None:
                print("Org not found:", orgName)
                return False
            time.sleep(3)
            b.click()
            MyPrintLog("clicked org")
            time.sleep(10)
        time.sleep(5)
        
        # self.driver.refresh()
        try:
            org = wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.cursorPointer"))
            MyPrintLog("Adding account to org: ", org.text)
        except:
            print("org not found")
            self.driver.save_screenshot("eror.png")
            # if self.email.lower() != "arnav@icedautomations.com" and (orgName is not None) and (orgName != ""):
            return False
        # time.sleep(500)

        # if self.find_element_by_inner_html(
        #         f"{email}", innerMost=True) is not None:
        #     MyPrintLog("Already added account")
        #     return
        
        self.driver.get("https://app.instantly.ai/app/accounts")
        
        try:
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.MuiButton-contained")).click()
            # MyPrintLog("1")
            time.sleep(5)
            self.find_element_by_inner_html(
                "Gmail / G-Suite", innerMost=True).click()
            # MyPrintLog("2")
            time.sleep(2)
            
            a = wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.MuiButtonBase-root"))
            self.simClick(a)
            
            # MyPrintLog("3")
            time.sleep(2)
            self.find_element_by_inner_html(
                "Option 1: oAuth", innerMost=True, click=True)
            # MyPrintLog("4")
            time.sleep(4)
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.MuiButton-contained")).click()
            # self.driver.implicitly_wait(3)

            window_after = self.driver.window_handles[1]
            self.driver.switch_to.window(window_after)
            self.driver.implicitly_wait(5)
            MyPrintLog("Switched to new window")
            self.signInGoogle(email, password)
            self.find_element_by_inner_html("Continue", innerMost=True).click()
            time.sleep(5)
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "#submit_approve_access")).click()
            time.sleep(5)
            MyPrintLog("Added account ", email)
        except Exception as e:
            print(
                type(e).__name__,          # TypeError
                __file__,                  # /tmp/example.py
                e.__traceback__.tb_lineno  # 2
            )
            self.driver.save_screenshot(f"errorpng/{email}.png")
            
        
    def handlePhoneverification(self, num_inp):
        data = getNumber()
        print(data)
        num_inp.send_keys("+" + str(data["number"]))
        self.find_element_by_inner_html("Next", innerMost=True).click()
        time.sleep(10)
        sms = getSMS(data["orderid"])
        print(sms)
        if sms is not None:
            self.driver.find_element(
                By.CSS_SELECTOR, 'input#idvAnyPhonePin').send_keys(sms)
            time.sleep(2)
            self.find_element_by_inner_html("Next", innerMost=True).click()
        else:
            print("handlePhoneverification: SMS not found")
        
        # input#idvAnyPhonePin
    
    def wait_for_element(self, selector, max_time=15):
        for i in range(max_time):
            try:
                return self.driver.find_element(By.CSS_SELECTOR, selector)
            except:
                time.sleep(1)
                continue
            
    def solveifcaptcha(self):
        try:
            a = self.wait_for_element(
                'img[alt="CAPTCHA image of text used to distinguish humans from robots"]')
            if a:
                # print("Captcha found")
                time.sleep(5)
                try:
                    base64 = a.screenshot_as_base64
                except:
                    print("caption image not found")
                    self.driver.save_screenshot("error/captcha_error.png")
                    # sys.exit()
                    # self.driver.close()
                    return
                # print(base64)
                print("Please solve the captcha")
                b = self.wait_for_element(
                    'input[aria-label="Type the text you hear or see"]')
                if not b:
                    print("captcha input not found")
                    return
                # print(b)
                ans = solve_captcha(base64)
                if not ans:
                    return
                b.send_keys(ans)
                time.sleep(2)
                self.wait_for_element("#identifierNext span").click()
                time.sleep(15)
                self.solveifcaptcha()
            else:
                print("Captcha not found")
        except:
            traceback.print_exc()

    def signInGoogle(self, email, password):
        wait = WebDriverWait(self.driver, 10)
        wait.until(lambda driver: driver.find_element(
            By.CSS_SELECTOR, "input#identifierId")).send_keys(email)
        time.sleep(3)
        self.find_element_by_inner_html("Next", innerMost=True).click()
        time.sleep(5)
        self.solveifcaptcha()
        wait.until(lambda driver: driver.find_element(
            By.CSS_SELECTOR, "#password .whsOnd")).send_keys(password)
        time.sleep(3)
        self.find_element_by_inner_html("Next", innerMost=True).click()
        time.sleep(5)
        MyPrintLog("Entered email and password")
        
        try:
            num_inp = wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, 'input[id="phoneNumberId"]'))
            if num_inp is not None:
                print("Phone verification found")
                self.handlePhoneverification(num_inp)
            else:
                print("No phone verification")
        except Exception as e:
            print("Error No phone verification")
        
        try:
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "input#confirm")).click()
        except:
            MyPrintLog("No confirm button")
            

        time.sleep(5)

    def getIMAPStatus(self, email, password):
        self.driver.get("https://mail.google.com/mail/u/0/#settings/fwdandpop")
        self.signInGoogle(email, password)
        self.driver.get("https://mail.google.com/mail/u/0/#settings/fwdandpop")
        # MyPrintLog("Opened settings")
        # MyPrintLog(self.driver.current_url)
        time.sleep(5)
        for i in range(3):
            try:
                a = self.find_element_by_inner_html(
                    "IMAP is enabled", innerMost=True)
                if a is not None:
                    return True
            except:
                self.driver.refresh()

    def signInMicrosoft(self, email, password, screenshot_dir=None, account_suffix=""):
        try:
            wait = WebDriverWait(self.driver, 10)
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, 'input[type="email"]')).send_keys(email)
            time.sleep(3)
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, 'input[type="submit"]')).click()
            time.sleep(5)
            self._screenshot_step(screenshot_dir, "ms_01_after_email", account_suffix)
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, 'input[name="passwd"]')).send_keys(password)
            time.sleep(3)
            
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, 'input[type="submit"]')).click()
            time.sleep(5)
            self._screenshot_step(screenshot_dir, "ms_02_after_password", account_suffix)
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, 'input[data-report-event="Signin_Submit"]')).click()
            try:
                a = wait.until(lambda driver: driver.find_element(
                    By.CSS_SELECTOR, 'input[type="submit"]'))
                if a is not None:
                    a.click()
            except:
                MyPrintLog("no stay signed in")
            # wait.until(lambda driver: driver.find_element(
            #     By.CSS_SELECTOR, "input.win-button")).click()
            #self.driver.save_screenshot(f"instantly_after_login.png")
            time.sleep(5)
            self._screenshot_step(screenshot_dir, "ms_03_after_stay_signed_in", account_suffix)
            MyPrintLog("Entered email and password")
        except Exception as e:
            self._screenshot_step(screenshot_dir, "ms_error", account_suffix)
            traceback.print_exc()
        
        # try:
        #     wait.until(lambda driver: driver.find_element(
        #         By.CSS_SELECTOR, """div[data-bind="text: str['STR_ChangePassword_Title']"]"""))
        #     print("Update password found")
        #     wait.until(lambda driver: driver.find_element(
        #         By.CSS_SELECTOR, "input#currentPassword")).send_keys(password)
        #     wait.until(lambda driver: driver.find_element(
        #         By.CSS_SELECTOR, "input#newPassword")).send_keys("changeTHIS@6565")
        #     wait.until(lambda driver: driver.find_element(
        #         By.CSS_SELECTOR, "input#confirmNewPassword")).send_keys("changeTHIS@6565")
        #     wait.until(lambda driver: driver.find_element(
        #         By.CSS_SELECTOR, 'input[type="submit"]')).click()
        # except:
        #     MyPrintLog("No Update password")
        # time.sleep(8)
        # try:
        #     a = self.find_element_by_inner_html(
        #         "Yes", innerMost=True)
        #     a.click()
        # except:
        #     MyPrintLog("No confirm button")
        
        

        # try:
        #     wait.until(lambda driver: driver.find_element(
        #         By.CSS_SELECTOR, 'input[type="submit"]')).click()
        #     print("Clicked submit")
        # except:
        #     MyPrintLog("No Accept button")
            
        # self.driver.save_screenshot(f"instantly_mfa.png")
        
        # try:
        #     try:
        #         a = wait.until(lambda driver: driver.find_element(
        #             By.CSS_SELECTOR, 'a[id="moreInfoLink"]'))
        #         if a is not None:
        #             print("More info link found")
        #             wait.until(lambda driver: driver.find_element(
        #                 By.CSS_SELECTOR, 'input[type="submit"]')).click()
        #             time.sleep(5)
        #     except:
        #         self.driver.save_screenshot(f"instantly2.png")
        #         MyPrintLog("No more info link")
                
        #     try:
            
        #         b = wait.until(lambda driver: driver.find_element(
        #             By.CSS_SELECTOR, 'a[href="https://aka.ms/getMicrosoftAuthenticator"]'))
        #         if b is not None:
        #             print("Authenticator link found")
        #             wait.until(lambda driver: driver.find_element(
        #                 By.CSS_SELECTOR, 'button:nth-child(2)')).click()
        #             time.sleep(5)
        #         wait.until(lambda driver: driver.find_element(
        #             By.CSS_SELECTOR, 'input[type="submit"]')).click()
        #     except:
        #         self.driver.save_screenshot(f"instantly3.png")
                
        #         MyPrintLog("No authenticator link")
        # except:
        #     self.driver.save_screenshot(f"instantly_mfa_error.png")
            
        #     MyPrintLog("some error in MFA")
        
    def fastclick(self, txt):
        script = f'''
        document.evaluate('//*[contains(text(), \"{txt}\")]', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue.click();
        '''
        self.driver.execute_script(script)

    def _screenshot_step(self, screenshot_dir, step_name, suffix=""):
        """If screenshot_dir is set, save screenshot; otherwise just print the step."""
        label = (step_name + "_" + suffix).strip("_") if suffix else step_name
        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)
            safe_name = label.replace(" ", "_").replace("/", "-")
            path = os.path.join(screenshot_dir, f"{safe_name}.png")
            try:
                self.driver.save_screenshot(path)
                MyPrintLog("Screenshot saved:", path)
            except Exception as e:
                MyPrintLog("Screenshot failed:", e)
        else:
            MyPrintLog("Step:", label)
    
    def addOutlookAccount(self, email, password, orgName, screenshot_dir=None):
        suf = email.replace("@", "_at_").replace(".", "_") if email else ""
        if self.driver.current_url != "https://app.instantly.ai/app/accounts":
            self.driver.get("https://app.instantly.ai/app/accounts")
        time.sleep(5)
        self._screenshot_step(screenshot_dir, "01_accounts_page", suf)
        wait = WebDriverWait(self.driver, 30)

        try:
          if self.email.lower() == "arnav@icedautomations.com" or self.email.lower() == "abhishek@icedautomations.com":
                print("Selecting org")
                self.driver.save_screenshot("instantly_org_select.png")
                # Icedautomations dropdown: first button in div.mb-3.d-flex (MuiButton-containedPrimary)
                wait.until(lambda driver: driver.find_element(
                    By.XPATH, "//button[.//span[contains(text(), 'Icedautomations')]]")).click()
                print("Clicked org dropdown, waiting for Neuralseek option")
                time.sleep(5)
                # 5th option in the opened dropdown list (scope to listbox so we don't match other lists)
                wait.until(lambda driver: driver.find_element(
                    By.CSS_SELECTOR, "[role='menu'] li:nth-child(13)")).click()
        except Exception as e:
            print("Error in org selection")
            print(e) 

        if orgName is not None and orgName != "":
            # MyPrintLog("Adding account for ", orgName)
            a = wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.cursorPointer"))
            self.simClick(a)
            # time.sleep(4)
            # c = self.driver.find_element(By.CSS_SELECTOR, "div > li:nth-child(2)")
            # self.simClick(c)
            b = self.find_element_by_inner_html(
                orgName, innerMost=True, click=True)
            if b == None:
                print("Org not found:", orgName)
                return False
            time.sleep(3)
            b.click()
            MyPrintLog("clicked org")
            time.sleep(10)
        time.sleep(5)
        self._screenshot_step(screenshot_dir, "02_after_org", suf)
        
        # self.driver.refresh()
        try:
            org = wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.cursorPointer"))
            MyPrintLog("Adding account to org: ", org.text)
        except:
            print("org not found")
            self.driver.save_screenshot("eror.png")
            self._screenshot_step(screenshot_dir, "error_org_not_found", suf)
            # if self.email.lower() != "arnav@icedautomations.com" and (orgName is not None) and (orgName != ""):
            return False
        # time.sleep(500)

        # if self.find_element_by_inner_html(
        #         f"{email}", innerMost=True) is not None:
        #     MyPrintLog("Already added account")
        #     return
        
        if self.driver.current_url != "https://app.instantly.ai/app/accounts":
            self.driver.get("https://app.instantly.ai/app/accounts")
        time.sleep(5)
        self._screenshot_step(screenshot_dir, "03_accounts_page_again", suf)
        
        try:
            wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.MuiButton-contained")).click()
            # MyPrintLog("1")
            time.sleep(5)
            self._screenshot_step(screenshot_dir, "04_add_account_modal", suf)
            try:
                self.fastclick("Office 365 / Outlook")
                time.sleep(2)
            except:
                self.driver.get("https://app.instantly.ai/app/account/connect")
                time.sleep(5)
                self.fastclick("Office 365 / Outlook")
                time.sleep(2)
            self._screenshot_step(screenshot_dir, "05_office365_selected", suf)
            self.simClick(wait.until(lambda driver: driver.find_element(
                By.CSS_SELECTOR, "button.MuiButtonBase-root")))
            time.sleep(5)
            self._screenshot_step(screenshot_dir, "06_before_switch_window", suf)
            
            window_after = self.driver.window_handles[1]
            self.driver.switch_to.window(window_after)
            self.driver.implicitly_wait(5)
            MyPrintLog("Switched to new window")
            self._screenshot_step(screenshot_dir, "07_outlook_login_window", suf)
            self.driver.save_screenshot(f"instantly_outlook_login.png")
            self.signInMicrosoft(email, password, screenshot_dir=screenshot_dir, account_suffix=suf)
            time.sleep(30)
            self._screenshot_step(screenshot_dir, "08_after_ms_signin", suf)
            MyPrintLog("Added account ", email)
        except Exception as e:
            print(e)
            self.driver.save_screenshot(f"errorpng/{email}.png")
            self._screenshot_step(screenshot_dir, "error_exception", suf)