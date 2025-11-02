#!/usr/bin/env python3
"""
Windows-ready automation flow:

- Prompts:
    * spot number  -> used to build C:\smsng_spot{spot}
    * profile num  -> used to build profile{profile}
    * email        -> the email to enter into input#account

- Launches Chrome (undetected-chromedriver) with the chosen user-data folder and profile.
- (optional) clicks "Sign in" if present.
- fills the account input (id="account"), toggles the checkbox, clicks Next (data-testid='test-button-next').
- On errors, saves screenshots to the current working directory.
"""
import os
import time
import ssl
import certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

# ----------------- Configuration -----------------
OKX_URL              = "https://v3.account.samsung.com/dashboard/intro"  # or change to /security if you prefer
CHROME_MAJOR_VERSION = 141
FIXED_PASSWORD       = "@Smsng#0961"  # kept for reference (not automatically used here)
DEFAULT_WAIT_SECONDS = 20
SCREENSHOT_ON_ERROR  = True
# -------------------------------------------------

def ask(prompt, required=True):
    """Simple console prompt that enforces a non-empty value when required."""
    while True:
        v = input(prompt).strip()
        if required and not v:
            print("Please enter a value.")
            continue
        return v

def safe_click(driver, element):
    """Scroll element into view and click it, with JS fallback."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.15)
        element.click()
        return True
    except (ElementClickInterceptedException, ElementNotInteractableException):
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception as e:
            print(f"[ERROR] JS click failed: {e}")
            return False
    except Exception as e:
        print(f"[ERROR] safe_click unexpected error: {e}")
        return False

def click_sign_in_button(driver, wait_seconds=8):
    """Click 'Sign in' if present (multiple strategies). Returns True if clicked."""
    wait = WebDriverWait(driver, wait_seconds)
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Sign in']")))
        print("[+] Found Sign in (exact text). Clicking...")
        return safe_click(driver, btn)
    except TimeoutException:
        pass

    # fallback: known css class
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button.css-hrwkno")
        print("[+] Found Sign in (css-hrwkno). Clicking...")
        return safe_click(driver, btn)
    except NoSuchElementException:
        pass

    # last resort: contains 'Sign'
    try:
        btn = driver.find_element(By.XPATH, "//button[contains(normalize-space(.), 'Sign')]")
        print("[+] Found Sign in (contains 'Sign'). Clicking...")
        return safe_click(driver, btn)
    except NoSuchElementException:
        pass

    print("[*] Sign in button not found; skipping.")
    return False

def fill_account_email(driver, email, wait_seconds=DEFAULT_WAIT_SECONDS):
    """Fill the input with id='account' (fallback to name='account')."""
    wait = WebDriverWait(driver, wait_seconds)
    input_el = None
    try:
        input_el = wait.until(EC.presence_of_element_located((By.ID, "account")))
        print("[+] Found input by id='account'")
    except TimeoutException:
        try:
            input_el = driver.find_element(By.NAME, "account")
            print("[+] Found input by name='account' (fallback)")
        except NoSuchElementException:
            print("[ERROR] account input not found by id or name.")
            return False

    try:
        input_el.clear()
        time.sleep(0.1)
        input_el.send_keys(email)
        # React/MUI may need blur to register the value
        input_el.send_keys(Keys.TAB)
        print(f"[+] Entered email: {email}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to enter email: {e}")
        return False

def ensure_checkbox_checked(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
    """
    Ensure the checkbox is checked using multiple approaches:
      - click input
      - click parent label
      - set via JS and dispatch events (for React)
    """
    wait = WebDriverWait(driver, wait_seconds)
    selectors = [
        (By.CSS_SELECTOR, "input.PrivateSwitchBase-input[type='checkbox']"),
        (By.CSS_SELECTOR, "input.css-1m9pwf3[type='checkbox']"),
        (By.XPATH, "//input[@type='checkbox' and contains(@class, 'PrivateSwitchBase-input')]"),
        (By.XPATH, "//input[@type='checkbox']"),
    ]
    checkbox = None
    for by, sel in selectors:
        try:
            checkbox = wait.until(EC.presence_of_element_located((by, sel)))
            print(f"[+] Found checkbox using selector: {sel}")
            break
        except TimeoutException:
            continue

    if not checkbox:
        print("[ERROR] Checkbox input not found.")
        return False

    try:
        is_checked = checkbox.get_attribute("checked") or checkbox.is_selected()
        if is_checked:
            print("[*] Checkbox already checked.")
            return True

        # Try to click the input directly (may be hidden)
        if safe_click(driver, checkbox):
            time.sleep(0.25)
            is_checked_after = checkbox.get_attribute("checked") or checkbox.is_selected()
            if is_checked_after:
                print("[+] Checkbox clicked successfully.")
                return True

        # Try clicking parent label (common pattern with hidden inputs)
        try:
            parent_label = checkbox.find_element(By.XPATH, "./ancestor::label[1]")
            print("[*] Clicking parent label to toggle checkbox...")
            if safe_click(driver, parent_label):
                time.sleep(0.25)
                is_checked_after = checkbox.get_attribute("checked") or checkbox.is_selected()
                if is_checked_after:
                    print("[+] Checkbox toggled via parent label.")
                    return True
        except NoSuchElementException:
            pass

        # Last-resort: set via JS and dispatch events so React notices
        print("[*] Using JS to set checkbox.checked = true and dispatch events.")
        driver.execute_script("""
            const cb = arguments[0];
            cb.checked = true;
            cb.dispatchEvent(new Event('input', { bubbles: true }));
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        """, checkbox)
        time.sleep(0.2)
        is_checked_final = checkbox.get_attribute("checked") or checkbox.is_selected()
        if is_checked_final:
            print("[+] Checkbox set via JS.")
            return True
        else:
            print("[ERROR] Checkbox still not checked after JS attempt.")
            return False

    except Exception as e:
        print(f"[ERROR] Exception while toggling checkbox: {e}")
        return False

def click_next_button(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
    """Click the Next button (prefer data-testid='test-button-next')."""
    wait = WebDriverWait(driver, wait_seconds)
    try:
        next_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='test-button-next']")))
        print("[+] Found Next button by data-testid.")
        return safe_click(driver, next_btn)
    except TimeoutException:
        print("[!] Next button not found by data-testid, trying fallbacks...")

    fallbacks = [
        (By.CSS_SELECTOR, "button[data-log-id='next']"),
        (By.CSS_SELECTOR, "button.css-1yuroud"),
        (By.XPATH, "//button[normalize-space(text())='Next']"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Next')]"),
    ]
    for by, sel in fallbacks:
        try:
            next_btn = wait.until(EC.element_to_be_clickable((by, sel)))
            print(f"[+] Found Next button using fallback: {sel}")
            return safe_click(driver, next_btn)
        except TimeoutException:
            continue

    print("[ERROR] Could not locate a clickable Next button.")
    return False

def take_screenshot(driver, name="error_screenshot.png"):
    """Save a screenshot to the current working directory."""
    try:
        path = os.path.join(os.getcwd(), name)
        driver.save_screenshot(path)
        print(f"[+] Screenshot saved to {path}")
    except Exception as e:
        print(f"[ERROR] Failed to save screenshot: {e}")

def main():
    # Gather inputs for Windows-style flow
    spot = ask("Enter spot number (e.g. 1): ")
    profile_num = ask("Enter profile number (e.g. 1): ")
    email = ask("Enter email to submit (example@example.com): ")

    # Build Windows paths (C:\smsng_spot{spot}\profile{profile_num})
    BASE_USER_DATA_DIR = rf"C:\smsng_spot{spot}"
    PROFILE_FOLDER = f"profile{profile_num}"
    profile_path = os.path.join(BASE_USER_DATA_DIR, PROFILE_FOLDER)

    print("\nUsing:")
    print(f"  BASE_USER_DATA_DIR = {BASE_USER_DATA_DIR}")
    print(f"  PROFILE_FOLDER     = {PROFILE_FOLDER}")
    print(f"  PROFILE_PATH       = {profile_path}")
    print(f"  EMAIL              = {email}")
    print(f"  PASSWORD (fixed)   = {FIXED_PASSWORD}\n")

    # Ensure base directory exists (Chrome will create profile subfolder if needed)
    os.makedirs(BASE_USER_DATA_DIR, exist_ok=True)

    # Prepare Chrome options
    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={BASE_USER_DATA_DIR}")
    opts.add_argument(f"--profile-directory={PROFILE_FOLDER}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    # If you want to point to a specific Chrome binary on Windows, set it here
    chrome_bin = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin
        print(f"[+] Using Chrome binary at: {chrome_bin}")
    else:
        print("[*] Chrome binary not found at default location; using system default.")

    # Launch undetected-chromedriver (visible)
    driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, headless=False)
    try:
        driver.get(OKX_URL)
        driver.implicitly_wait(2)

        # OPTIONAL: click Sign in if present (some flows show sign-in first)
        try:
            click_sign_in_button(driver, wait_seconds=8)
        except Exception as e:
            print(f"[*] Sign-in attempt raised: {e} (continuing)")

        # small pause to let dynamic UI settle
        time.sleep(1)

        # 1) Fill account/email
        if not fill_account_email(driver, email, wait_seconds=DEFAULT_WAIT_SECONDS):
            print("[ERROR] Failed to fill the account input.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "fill_account_error.png")
            return

        time.sleep(0.6)

        # 2) Ensure checkbox is checked
        if not ensure_checkbox_checked(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
            print("[ERROR] Failed to check the required checkbox.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "checkbox_error.png")
            return

        time.sleep(0.4)

        # 3) Click Next
        # if not click_next_button(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
        #     print("[ERROR] Failed to click Next.")
        #     if SCREENSHOT_ON_ERROR:
        #         take_screenshot(driver, "next_button_error.png")
        #     return

        # print("[+] Next clicked successfully. Flow moved forward (if navigation occurred).")
        # # Allow a moment to observe the result
        # time.sleep(2)

        input("Press ENTER to close browser and quit...")

    except Exception as e:
        print(f"[ERROR] Unexpected exception in main flow: {e}")
        if SCREENSHOT_ON_ERROR:
            try:
                take_screenshot(driver, "unexpected_error.png")
            except Exception:
                pass
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
