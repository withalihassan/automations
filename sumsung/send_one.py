#!/usr/bin/env python3
"""
Windows-ready flow for phone verification (Samsung dashboard) with:
 - password popup handling
 - try country selection first
 - only close cookie popup if country selection fails
 - tightened cookie-close selectors to avoid false positives
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
OKX_PHONE_URL        = "https://v3.account.samsung.com/dashboard/security/phone"
CHROME_MAJOR_VERSION = 141
FIXED_PASSWORD       = "@Smsng#860"
DEFAULT_WAIT_SECONDS = 20
SCREENSHOT_ON_ERROR  = True
# -------------------------------------------------

def ask(prompt, required=True):
    while True:
        v = input(prompt).strip()
        if required and not v:
            print("Please enter a value.")
            continue
        return v

def safe_click(driver, element):
    """Scroll to element and click with JS fallback."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.12)
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

def enter_password_if_popup(driver, wait_seconds=8):
    """
    Detects a password popup and handles it:
    - enters FIXED_PASSWORD and clicks OK button.
    Returns True if popup handled (or not present), False on error.
    """
    wait = WebDriverWait(driver, wait_seconds)

    password_selectors = [
        (By.XPATH, "//input[@type='password' and contains(@class,'MuiInputBase-input')]"),
        (By.XPATH, "//input[@type='password' and contains(@aria-describedby, '-helper-text')]"),
        (By.CSS_SELECTOR, "input[type='password']"),
    ]

    password_input = None
    for by, sel in password_selectors:
        try:
            password_input = wait.until(EC.presence_of_element_located((by, sel)))
            print(f"[+] Password input detected using selector: {sel}")
            break
        except TimeoutException:
            continue

    if not password_input:
        print("[*] No password popup detected (continuing).")
        return True

    try:
        password_input.clear()
        password_input.send_keys(FIXED_PASSWORD)
        password_input.send_keys(Keys.TAB)
        print("[+] Entered fixed password into popup field.")

        # Click OK button (prefer data-testid)
        try:
            ok_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='test-button-ok']")))
            print("[+] Found OK button by data-testid; clicking...")
            if not safe_click(driver, ok_btn):
                raise RuntimeError("OK click failed")
        except TimeoutException:
            try:
                ok_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='OK']")))
                print("[+] Found OK button by text; clicking...")
                if not safe_click(driver, ok_btn):
                    raise RuntimeError("OK click failed (text fallback)")
            except TimeoutException:
                print("[ERROR] OK button for password popup not found.")
                return False

        time.sleep(1)
        print("[+] Password popup handled.")
        return True
    except Exception as e:
        print(f"[ERROR] Exception while handling password popup: {e}")
        return False

def close_cookie_popup_if_present(driver, wait_seconds=3):
    """
    Close cookie/footer popup ONLY if a plausible close icon/button exists.
    Tight selectors used to avoid false positives:
      - button containing <img src*='close' or alt contains 'close'
      - button with exact css class 'css-10snoxe' (from your provided HTML)
    Returns True if we clicked a close, False if none found.
    """
    wait = WebDriverWait(driver, wait_seconds)
    # prioritized selectors (precise)
    selectors = [
        # image with src containing 'close' inside a button
        (By.XPATH, "//button[.//img[contains(@src,'close') or contains(@alt,'close')]]"),
        # image element itself (will click ancestor button)
        (By.XPATH, "//img[contains(@src,'close') or contains(@alt,'close')]"),
        # button with the specific CSS token you gave earlier (likely the cookie close)
        (By.CSS_SELECTOR, "button.css-10snoxe"),
        # a button that contains an SVG or IMG with 'close' in src — slightly broader but still targeted
        (By.XPATH, "//button[.//svg[contains(@class,'close')]]"),
    ]

    for by, sel in selectors:
        try:
            el = wait.until(EC.presence_of_element_located((by, sel)))
            if el is None:
                continue
            # If it's an img, find its parent button
            if el.tag_name.lower() == "img":
                try:
                    btn = el.find_element(By.XPATH, "./ancestor::button[1]")
                    print("[*] Found cookie close image; clicking ancestor button.")
                    safe_click(driver, btn)
                except Exception:
                    print("[*] Found image but couldn't locate ancestor button; trying JS click on image.")
                    driver.execute_script("arguments[0].click();", el)
            else:
                print(f"[*] Found cookie/close button using selector: {sel}. Clicking...")
                safe_click(driver, el)
            time.sleep(0.45)  # allow popup to close
            return True
        except TimeoutException:
            continue
        except Exception as e:
            print(f"[WARN] while trying to close cookie popup with selector {sel}: {e}")
            continue

    # not found
    print("[*] No cookie/footer close button detected (targeted selectors).")
    return False

def select_country_uk(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
    """
    Clicks the country combobox and selects United Kingdom (+44).
    This handles MUI portal lists by searching for list items globally.
    """
    wait = WebDriverWait(driver, wait_seconds)
    try:
        combobox = wait.until(EC.element_to_be_clickable((By.ID, "county-calling-code-select")))
        print("[+] Found country combobox (county-calling-code-select). Clicking to open list...")
        if not safe_click(driver, combobox):
            print("[ERROR] Failed to click country combobox.")
            return False
    except TimeoutException:
        print("[ERROR] Country combobox (county-calling-code-select) not found.")
        return False

    # give list time to render (MUI often uses a portal)
    try:
        WebDriverWait(driver, 6).until(lambda d: (
            (d.find_element(By.ID, "county-calling-code-select").get_attribute("aria-expanded") == "true")
            or len(d.find_elements(By.XPATH, "//ul[@role='listbox'] | //div[@role='listbox']")) > 0
        ))
    except Exception:
        # continue - sometimes aria-expanded isn't updated quickly
        pass

    time.sleep(0.25)

    # Try targeted strategies in order
    strategies = [
        ("data-value", "//li[@data-value='GB']"),
        ("by-text", "//li[contains(normalize-space(.), 'United Kingdom') or contains(normalize-space(.), 'United Kingdom (+44)')]"),
        ("by-plus44", "//li[contains(normalize-space(.), '+44')]"),
    ]

    for name, xpath in strategies:
        try:
            candidates = driver.find_elements(By.XPATH, xpath)
            if not candidates:
                continue
            for cand in candidates:
                text = cand.text.strip()
                dv = cand.get_attribute("data-value")
                if dv and dv.strip().upper() == "GB":
                    print(f"[+] Clicking UK option (data-value='GB') -> text: {text}")
                    if safe_click(driver, cand):
                        time.sleep(0.4)
                        return True
                if "United Kingdom" in text or "+44" in text:
                    print(f"[+] Clicking UK-like option (text match) -> text: {text}")
                    if safe_click(driver, cand):
                        time.sleep(0.4)
                        return True
            # fallback: JS click first candidate
            first = candidates[0]
            print(f"[*] Candidates found by {name}; trying first via JS: '{first.text.strip()[:60]}'")
            try:
                driver.execute_script("arguments[0].click();", first)
                time.sleep(0.4)
                return True
            except Exception as e:
                print(f"[WARN] JS click failed for {name}: {e}")
                continue
        except Exception as e:
            print(f"[WARN] strategy {name} raised: {e}")
            continue

    # failed selection
    print("[ERROR] Could not select United Kingdom (+44) from country list.")
    # optional debug dump of first 20 li items
    try:
        all_li = driver.find_elements(By.XPATH, "//li")
        print("[DEBUG] Available <li> items (first 20):")
        for i, li in enumerate(all_li[:20], 1):
            try:
                dv = li.get_attribute("data-value")
                txt = li.text.strip().replace("\n", " | ")
                print(f"  {i}. data-value={dv} text='{txt[:140]}'")
            except Exception:
                continue
    except Exception as e:
        print(f"[DEBUG] Failed to dump <li> items: {e}")

    return False

def enter_phone_and_send_code(driver, phone, wait_seconds=DEFAULT_WAIT_SECONDS):
    """Enter the phone number into #phoneNumber and click Send code button."""
    wait = WebDriverWait(driver, wait_seconds)
    try:
        phone_input = wait.until(EC.presence_of_element_located((By.ID, "phoneNumber")))
        print("[+] Found phone input (#phoneNumber). Entering phone number...")
        phone_input.clear()
        time.sleep(0.1)
        phone_input.send_keys(phone)
        phone_input.send_keys(Keys.TAB)
        time.sleep(0.3)
    except TimeoutException:
        print("[ERROR] Phone input (#phoneNumber) not found.")
        return False

    # Click Send code (try text then class then pattern)
    try:
        send_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Send code']")))
        print("[+] Found Send code button by text. Clicking...")
        if safe_click(driver, send_btn):
            return True
    except TimeoutException:
        pass

    try:
        send_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.css-1socum8")))
        print("[+] Found Send code button by class css-1socum8. Clicking...")
        if safe_click(driver, send_btn):
            return True
    except TimeoutException:
        pass

    try:
        send_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'MuiButton-subButton') and contains(normalize-space(.),'Send code')]")))
        print("[+] Found Send code button by class pattern. Clicking...")
        if safe_click(driver, send_btn):
            return True
    except TimeoutException:
        pass

    print("[ERROR] Could not find/click the Send code button.")
    return False

def wait_for_verification_message(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
    """Wait for 'The verification code has been sent.' message and return it."""
    wait = WebDriverWait(driver, wait_seconds)
    try:
        elem = wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(normalize-space(.), 'The verification code has been sent')]")))
        text = elem.text.strip()
        print(f"[+] Message found: {text}")
        return text
    except TimeoutException:
        print("[ERROR] Verification-sent message did not appear within timeout.")
        return None

def take_screenshot(driver, name="error_screenshot.png"):
    try:
        path = os.path.join(os.getcwd(), name)
        driver.save_screenshot(path)
        print(f"[+] Screenshot saved to {path}")
    except Exception as e:
        print(f"[ERROR] Failed to save screenshot: {e}")

def main():
    print("=== Samsung phone verification flow (Windows) ===")
    spot = ask("Enter spot number (e.g. 1): ")
    profile_num = ask("Enter profile number (e.g. 1): ")
    phone = ask("Enter phone number (no country code; digits only, e.g. 7123456789): ")

    BASE_USER_DATA_DIR = rf"C:\smsng_spot{spot}"
    PROFILE_FOLDER = f"profile{profile_num}"
    profile_path = os.path.join(BASE_USER_DATA_DIR, PROFILE_FOLDER)

    print("\nUsing:")
    print(f"  BASE_USER_DATA_DIR = {BASE_USER_DATA_DIR}")
    print(f"  PROFILE_FOLDER     = {PROFILE_FOLDER}")
    print(f"  PROFILE_PATH       = {profile_path}")
    print(f"  PHONE              = {phone}")
    print(f"  COUNTRY            = United Kingdom (+44)")
    print(f"  FIXED_PASSWORD     = {FIXED_PASSWORD}\n")

    os.makedirs(BASE_USER_DATA_DIR, exist_ok=True)

    # Chrome options
    opts = uc.ChromeOptions()
    # --- Enable Headless Mode (modern method) ---
    opts.add_argument("--headless=new")       # Use new headless for Chrome 109+
    opts.add_argument("--disable-gpu")        # Disable GPU (for compatibility)
    opts.add_argument("--window-size=1920,1080")  # Set fixed window size
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-desv-shm-usage")
    opts.add_argument(f"--user-data-dir={BASE_USER_DATA_DIR}")
    opts.add_argument(f"--profile-directory={PROFILE_FOLDER}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    chrome_bin = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin
        print(f"[+] Using Chrome binary at: {chrome_bin}")
    else:
        print("[*] Chrome binary not found at default; using system default.")

    driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, headless=False)
    try:
        driver.get(OKX_PHONE_URL)
        driver.implicitly_wait(2)
        time.sleep(1)  # let page render

        # 1) Optional password popup handling (first)
        handled = enter_password_if_popup(driver, wait_seconds=6)
        if not handled:
            print("[ERROR] Password popup handling failed.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "password_popup_error.png")
            return

        time.sleep(0.4)

        # 2) Try selecting the country FIRST (if it works, no cookie handling needed)
        print("[*] Attempting country selection (first try)...")
        if select_country_uk(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
            print("[+] Country selected on first try (no cookie close needed).")
        else:
            print("[*] Country selection failed on first try — attempting to close cookie/footer popup and retry.")
            # Only now try to close cookie popup (tight selectors)
            close_cookie_popup_if_present(driver, wait_seconds=3)
            time.sleep(0.5)
            # Retry country selection once more
            if select_country_uk(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
                print("[+] Country selected after closing cookie popup.")
            else:
                print("[ERROR] Selecting country (UK) failed even after closing cookie popup.")
                if SCREENSHOT_ON_ERROR:
                    take_screenshot(driver, "select_country_error.png")
                return

        time.sleep(0.6)

        # 3) Enter phone number and click Send code
        if not enter_phone_and_send_code(driver, phone, wait_seconds=DEFAULT_WAIT_SECONDS):
            print("[ERROR] Entering phone or clicking Send code failed.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "send_code_error.png")
            return

        print("[*] Send code clicked — waiting for verification message...")

        # 4) Wait for verification message and print it
        msg = wait_for_verification_message(driver, wait_seconds=DEFAULT_WAIT_SECONDS)
        if msg:
            print(f"\n=== Verification message ===\n{msg}\n============================\n")
        else:
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "verification_message_missing.png")
            return

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
