#!/usr/bin/env python3
"""
Windows-ready Samsung signup flow (human-like) with strict cookie-close handling.

Flow:
 - Prompts: spot id -> builds C:\smsng_spot{spot}, profile id -> profile{profile}, email
 - Opens: https://v3.account.samsung.com/dashboard/security/phone
 - If strict cookie close button exists (exact selector + close.svg image) click it first
 - Click Sign in -> Create account
 - Ensure 'all' checkbox is checked (reliably) BEFORE clicking Agree
 - Click Agree and fill signup form (email, password, confirm, names, DOB)
 - Uses human-like typing/delays, explicit waits, and robust fallbacks
"""
import os
import time
import random
import ssl
import certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    ElementClickInterceptedException, ElementNotInteractableException,
)

# ---------------- Configuration ----------------
OKX_PHONE_URL        = "https://v3.account.samsung.com/dashboard/security/phone"
CHROME_MAJOR_VERSION = 141
FIXED_PASSWORD       = "@Smsng#860"
DEFAULT_WAIT_SECONDS = 20
SCREENSHOT_ON_ERROR  = True
# -----------------------------------------------

FIRST_NAMES = ["Adam", "Bilal", "Omar", "Usman", "Aamir", "Sara", "Ayesha", "Nadia", "Zara", "Hassan", "Ali", "Ibrahim"]
LAST_NAMES  = ["Khan", "Ahmed", "Hussain", "Malik", "Farooq", "Abbasi", "Saeed", "Raza", "Iqbal", "Shah"]

# ---------- Helpers ----------
def human_delay(a=0.08, b=0.18):
    time.sleep(random.uniform(a, b))

def human_type(el, text, min_delay=0.03, max_delay=0.12):
    try:
        el.clear()
    except Exception:
        pass
    for ch in text:
        el.send_keys(ch)
        time.sleep(random.uniform(min_delay, max_delay))
    human_delay(0.08, 0.18)

def take_screenshot(driver, name="error_screenshot.png"):
    try:
        path = os.path.join(os.getcwd(), name)
        driver.save_screenshot(path)
        print(f"[+] Screenshot saved: {path}")
    except Exception as e:
        print(f"[WARN] Screenshot failed: {e}")

def safe_js_click(driver, el):
    try:
        driver.execute_script("arguments[0].click();", el)
        return True
    except Exception as e:
        print(f"[WARN] JS click failed: {e}")
        return False

def safe_action_click(driver, el):
    try:
        actions = ActionChains(driver)
        actions.move_to_element(el).pause(random.uniform(0.05,0.18)).click(el).perform()
        return True
    except Exception:
        return safe_js_click(driver, el)

def wait_visible(driver, by, selector, timeout=DEFAULT_WAIT_SECONDS):
    return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((by, selector)))

def wait_clickable(driver, by, selector, timeout=DEFAULT_WAIT_SECONDS):
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector)))

# ---------- Strict cookie close ----------
def close_cookie_strict(driver, wait_seconds=3):
    """
    Strictly target this exact cookie-close button:
    button.MuiButtonBase-root.MuiIconButton-root.MuiIconButton-sizeMedium.css-10snoxe
    and verify its <img> src contains 'close.svg' before clicking.
    Returns True if clicked, False otherwise.
    """
    sel = "button.MuiButtonBase-root.MuiIconButton-root.MuiIconButton-sizeMedium.css-10snoxe"
    try:
        el = WebDriverWait(driver, wait_seconds).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
    except TimeoutException:
        # not present
        return False

    try:
        # verify it contains an IMG whose src contains 'close.svg'
        try:
            img = el.find_element(By.TAG_NAME, "img")
            src = img.get_attribute("src") or ""
            if "close.svg" not in src and "close" not in src.lower():
                print("[WARN] Found cookie button matching class but image src doesn't contain 'close.svg' -> skipping to avoid false positive.")
                return False
        except NoSuchElementException:
            print("[WARN] Found cookie button matching class but no <img> inside -> skipping to avoid false positive.")
            return False

        print("[*] Strict cookie close button found and verified (clicking)...")
        safe_action_click(driver, el)
        human_delay(0.35, 0.6)
        return True
    except Exception as e:
        print(f"[WARN] Error while clicking strict cookie button: {e}")
        return False

# ---------- Flow functions ----------
def click_sign_in_then_createaccount(driver):
    # Sign in
    try:
        signbtn = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Sign in']")))
        print("[*] Clicking Sign in")
        safe_action_click(driver, signbtn)
        human_delay(0.6, 1.0)
    except TimeoutException:
        try:
            signbtn = driver.find_element(By.CSS_SELECTOR, "button.css-hrwkno")
            print("[*] Clicking Sign in (css-hrwkno fallback)")
            safe_action_click(driver, signbtn)
            human_delay(0.6, 1.0)
        except Exception:
            print("[*] Sign in not found; continuing")

    # Create account
    try:
        create = WebDriverWait(driver, 12).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "span[data-testid='test-button-createaccount']")))
        print("[*] Clicking Create account")
        safe_action_click(driver, create)
        human_delay(0.8, 1.2)
        return True
    except TimeoutException:
        try:
            create = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(normalize-space(.),'Create account') or @data-log-id='create-account']")))
            print("[*] Clicking Create account (fallback)")
            safe_action_click(driver, create)
            human_delay(0.8, 1.2)
            return True
        except TimeoutException:
            print("[ERROR] Create account element not found.")
            return False

def ensure_checkbox_checked_before_agree(driver):
    try:
        el_input = WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR, "input#all")))
    except TimeoutException:
        print("[WARN] Checkbox input#all not present (skipping check attempt).")
        return True

    def is_checked(el):
        try:
            val = el.get_attribute("checked")
            if val is None:
                return el.is_selected()
            if val in ["true", "checked", "1"] or val != "":
                return True
            return False
        except Exception:
            return False

    if is_checked(el_input):
        print("[*] 'all' checkbox already checked.")
        return True

    # Try clicking the input directly if visible
    try:
        if el_input.is_displayed() and el_input.is_enabled():
            try:
                safe_action_click(driver, el_input)
                human_delay(0.12, 0.28)
            except Exception:
                pass
            if is_checked(el_input):
                print("[+] Checkbox checked by clicking input.")
                return True
    except Exception:
        pass

    # Try parent label
    try:
        label = el_input.find_element(By.XPATH, "./ancestor::label[1]")
        if label:
            print("[*] Clicking parent label for checkbox")
            safe_action_click(driver, label)
            human_delay(0.12, 0.28)
            if is_checked(el_input):
                print("[+] Checkbox checked by clicking parent label.")
                return True
    except Exception:
        pass

    # Try clicking the visible checkbox span within label
    try:
        span_candidates = driver.find_elements(By.XPATH, "//label//span[contains(@class,'MuiButtonBase-root') and contains(@class,'MuiCheckbox-root')]")
        for s in span_candidates:
            try:
                safe_action_click(driver, s)
                human_delay(0.12, 0.28)
                if is_checked(el_input):
                    print("[+] Checkbox checked by clicking checkbox span.")
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # JS fallback
    try:
        print("[*] Using JS to set checkbox.checked = true and dispatch events (last resort).")
        driver.execute_script("""
            const cb = arguments[0];
            cb.checked = true;
            cb.dispatchEvent(new Event('input', { bubbles: true }));
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        """, el_input)
        human_delay(0.12, 0.28)
        if is_checked(el_input):
            print("[+] Checkbox set via JS.")
            return True
    except Exception as e:
        print(f"[WARN] JS checkbox set failed: {e}")

    if is_checked(el_input):
        return True
    print("[ERROR] Could not check 'all' checkbox after multiple attempts.")
    return False

def click_agree_button(driver):
    try:
        agree = WebDriverWait(driver, 12).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-log-id='agree']")))
        print("[*] Clicking Agree button")
        safe_action_click(driver, agree)
        human_delay(0.8, 1.2)
        return True
    except TimeoutException:
        print("[ERROR] Agree button not found/clickable.")
        return False

def fill_signup_form(driver, email):
    try:
        account_input = wait_visible(driver, By.ID, "account", timeout=20)
        print("[*] Typing email human-like.")
        human_type(account_input, email)
    except TimeoutException:
        print("[ERROR] Account input not visible.")
        return False

    try:
        pw_input = wait_visible(driver, By.ID, "password", timeout=8)
        conf_input = wait_visible(driver, By.ID, "confirmPassword", timeout=8)
        print("[*] Typing password.")
        human_type(pw_input, FIXED_PASSWORD)
        human_type(conf_input, FIXED_PASSWORD)
    except TimeoutException:
        print("[ERROR] Password fields missing.")
        return False

    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    try:
        fn_input = wait_visible(driver, By.ID, "firstName", timeout=8)
        ln_input = wait_visible(driver, By.ID, "lastName", timeout=8)
        print(f"[*] Typing name: {first_name} {last_name}")
        human_type(fn_input, first_name)
        human_type(ln_input, last_name)
    except TimeoutException:
        print("[ERROR] Name fields missing.")
        return False

    day_value = str(random.randint(1, 28)).zfill(2)
    try:
        day_input = wait_visible(driver, By.ID, "day", timeout=6)
        human_type(day_input, day_value)
        print(f"[*] Day entered: {day_value}")
    except TimeoutException:
        print("[ERROR] Day field missing.")
        return False

    month_value = random.choice([f"{i:02d}" for i in range(1,13)])
    try:
        month_select_el = wait_visible(driver, By.ID, "month", timeout=6)
        try:
            select = Select(month_select_el)
            select.select_by_value(month_value)
            print(f"[*] Month selected: {month_value}")
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", month_select_el, month_value)
            print(f"[*] Month set via JS fallback: {month_value}")
    except TimeoutException:
        print("[ERROR] Month select missing.")
        return False

    year_value = str(random.choice([2000,2001,2002,2003]))
    try:
        year_input = wait_visible(driver, By.ID, "year", timeout=6)
        human_type(year_input, year_value)
        print(f"[*] Year entered: {year_value}")
    except TimeoutException:
        print("[ERROR] Year field missing.")
        return False

    human_delay(0.5, 0.9)
    print("[+] Form filled (email, password, names, DOB).")
    return True

# ---------- Main ----------
def main():
    print("=== Samsung signup (human-like, strict cookie-close) ===")
    spot = input("Enter spot id (e.g. 1): ").strip()
    profile_id = input("Enter profile id (e.g. 1): ").strip()
    email = input("Enter email to use: ").strip()

    BASE_USER_DATA_DIR = rf"C:\smsng_spot{spot}"
    PROFILE_FOLDER = f"profile{profile_id}"
    os.makedirs(BASE_USER_DATA_DIR, exist_ok=True)

    print("\nUsing:")
    print(f"  BASE_USER_DATA_DIR = {BASE_USER_DATA_DIR}")
    print(f"  PROFILE_FOLDER     = {PROFILE_FOLDER}")
    print(f"  EMAIL              = {email}")
    print(f"  FIXED_PASSWORD     = {FIXED_PASSWORD}\n")

    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={BASE_USER_DATA_DIR}")
    opts.add_argument(f"--profile-directory={PROFILE_FOLDER}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    chrome_bin = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin
        print(f"[+] Using Chrome binary: {chrome_bin}")

    driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, headless=False)
    try:
        driver.get(OKX_PHONE_URL)
        driver.implicitly_wait(1)
        human_delay(0.6, 1.2)

        # STRICT: if exact cookie-close button exists, close it FIRST
        if close_cookie_strict(driver, wait_seconds=3):
            print("[+] Cookie/footer close clicked (strict).")
        else:
            print("[*] No strict cookie-close button detected; continuing.")

        # 1) Click Sign in -> Create account
        if not click_sign_in_then_createaccount(driver):
            print("[ERROR] Sign in / Create account step failed.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "sign_create_error.png")
            return

        # 2) Ensure checkbox is checked BEFORE clicking Agree
        if not ensure_checkbox_checked_before_agree(driver):
            print("[ERROR] Checkbox could not be checked.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "checkbox_fail.png")
            return

        human_delay(0.4, 0.9)

        # 3) Click Agree
        if not click_agree_button(driver):
            print("[ERROR] Agree click failed.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "agree_fail.png")
            return

        # 4) Fill the sign-up form
        if not fill_signup_form(driver, email):
            print("[ERROR] Sign-up form fill failed.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "fill_signup_fail.png")
            return

        print("\n[+] Script completed successfully (form filled).")
        time.sleep(250)
        input("Press ENTER to close browser and quit...")

    except Exception as e:
        print(f"[ERROR] Unexpected exception in main: {e}")
        if SCREENSHOT_ON_ERROR:
            try:
                take_screenshot(driver, "unexpected_main_error.png")
            except Exception:
                pass
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
