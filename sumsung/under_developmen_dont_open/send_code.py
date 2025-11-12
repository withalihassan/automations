#!/usr/bin/env python3
"""
Windows-ready flow for phone verification (Samsung dashboard).

Changes:
 - Phone is fetched from database using misc/num_fetcher.py and misc/range.txt
 - The number is *not* decremented immediately. After the flow succeeds
   (we detect the verification-sent message) we call lock_and_decrement()
   to decrement and mark it reserved/locked.
 - Project structure kept same (misc/*).
"""
import os
import sys
import time
import ssl
import certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

# Make sure misc/ is importable (works even without __init__.py)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MISC_DIR = os.path.join(SCRIPT_DIR, "misc")
if MISC_DIR not in sys.path:
    sys.path.insert(0, MISC_DIR)

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
import num_fetcher  # from misc/num_fetcher.py

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
    wait = WebDriverWait(driver, wait_seconds)
    selectors = [
        (By.XPATH, "//button[.//img[contains(@src,'close') or contains(@alt,'close')]]"),
        (By.XPATH, "//img[contains(@src,'close') or contains(@alt,'close')]"),
        (By.CSS_SELECTOR, "button.css-10snoxe"),
        (By.XPATH, "//button[.//svg[contains(@class,'close')]]"),
    ]

    for by, sel in selectors:
        try:
            el = wait.until(EC.presence_of_element_located((by, sel)))
            if el is None:
                continue
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
            time.sleep(0.45)
            return True
        except TimeoutException:
            continue
        except Exception as e:
            print(f"[WARN] while trying to close cookie popup with selector {sel}: {e}")
            continue

    print("[*] No cookie/footer close button detected (targeted selectors).")
    return False

def select_country_uk(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
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

    try:
        WebDriverWait(driver, 6).until(lambda d: (
            (d.find_element(By.ID, "county-calling-code-select").get_attribute("aria-expanded") == "true")
            or len(d.find_elements(By.XPATH, "//ul[@role='listbox'] | //div[@role='listbox']")) > 0
        ))
    except Exception:
        pass

    time.sleep(0.25)

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

    print("[ERROR] Could not select United Kingdom (+44) from country list.")
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

    # --- Fetch phone from DB (misc/num_fetcher.py) ---
    range_id = num_fetcher.read_range_id_from_file(num_fetcher.RANGE_FILE)
    if not range_id:
        print("[ERROR] No range_id available (check misc/range.txt). Exiting.")
        return

    conn = num_fetcher.get_db_connection()
    number_row = None
    try:
        number_row = num_fetcher.get_random_number(conn, range_id)
        if not number_row:
            print(f"[ERROR] No available numbers for range_id = {range_id}. Exiting.")
            return
        phone = str(number_row["number"])
        print(f"[+] Selected number (not reserved yet): {phone}")
    except Exception as e:
        print(f"[ERROR] Failed to fetch number from DB: {e}")
        return
    # NOTE: don't close conn yet because we'll need it later to call lock_and_decrement()

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

    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
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
        time.sleep(1)

        handled = enter_password_if_popup(driver, wait_seconds=6)
        if not handled:
            print("[ERROR] Password popup handling failed.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "password_popup_error.png")
            return

        time.sleep(0.4)

        print("[*] Attempting country selection (first try)...")
        if select_country_uk(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
            print("[+] Country selected on first try (no cookie close needed).")
        else:
            print("[*] Country selection failed on first try — attempting to close cookie/footer popup and retry.")
            close_cookie_popup_if_present(driver, wait_seconds=3)
            time.sleep(0.5)
            if select_country_uk(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
                print("[+] Country selected after closing cookie popup.")
            else:
                print("[ERROR] Selecting country (UK) failed even after closing cookie popup.")
                if SCREENSHOT_ON_ERROR:
                    take_screenshot(driver, "select_country_error.png")
                return

        time.sleep(0.6)

        if not enter_phone_and_send_code(driver, phone, wait_seconds=DEFAULT_WAIT_SECONDS):
            print("[ERROR] Entering phone or clicking Send code failed.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "send_code_error.png")
            return

        print("[*] Send code clicked — waiting for verification message...")

        msg = wait_for_verification_message(driver, wait_seconds=DEFAULT_WAIT_SECONDS)
        if msg:
            print(f"\n=== Verification message ===\n{msg}\n============================\n")
            # Successful flow: now decrement/lock the number in DB
            try:
                ok = num_fetcher.lock_and_decrement(conn, phone)
                if ok:
                    print(f"[+] Number {phone} locked and num_limit decremented successfully.")
                else:
                    print(f"[WARN] Failed to lock_and_decrement number {phone}. It may have been taken by another process.")
            except Exception as e:
                print(f"[ERROR] Exception while locking/decrementing number {phone}: {e}")
        else:
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "verification_message_missing.png")
            print("[ERROR] Verification message not seen; not decrementing the number.")
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
        try:
            conn.close()
        except Exception:
            pass
        driver.quit()

if __name__ == "__main__":
    main()
