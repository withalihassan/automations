#!/usr/bin/env python3
"""
Windows-only bulk Samsung signup script (human-like) using undetected_chromedriver.

Improvements over previous version:
 - Critical steps (Create account, Ensure checkbox, Click Agree, Fill form) have retries
   with refresh and backoff.
 - If a critical step ultimately fails, the worker will take a screenshot AND wait for the
   user to manually close that browser/profile instead of quitting it immediately.
 - Safe uc.Chrome() creation remains (serialized + cleanup retries) to avoid udc race issues.
 - All other robustness features preserved (strict cookie close, JS fallbacks, human typing).

Usage:
  python samsung_bulk_signup_windows_wait_on_fail.py
  python samsung_bulk_signup_windows_wait_on_fail.py --spots 1,2,3 --profile 1 --emails a@x.com,b@y.com
  python samsung_bulk_signup_windows_wait_on_fail.py --spots 1,2,3 --profile 1 --emails emails.txt --auto-close-timeout 60
"""
import os
import sys
import time
import random
import argparse
import threading
import ssl
import certifi
import traceback
from typing import List

ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# ---------------- Config ----------------
OKX_PHONE_URL = "https://v3.account.samsung.com/dashboard/security/phone"
CHROME_MAJOR_VERSION = 141
FIXED_PASSWORD = "@Smsng#860"
DEFAULT_WAIT_SECONDS = 25
SCREENSHOT_ON_ERROR = True
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SEC = 2
# ----------------------------------------

FIRST_NAMES = ["Adam", "Bilal", "Omar", "Usman", "Aamir", "Sara", "Ayesha", "Nadia", "Zara", "Hassan", "Ali", "Ibrahim"]
LAST_NAMES  = ["Khan", "Ahmed", "Hussain", "Malik", "Farooq", "Abbasi", "Saeed", "Raza", "Iqbal", "Shah"]

# Global lock to serialize uc.Chrome() creation (prevents unzip/rename race)
_uc_creation_lock = threading.Lock()

# ---------- Helpers ----------
def human_delay(a=0.08, b=0.18):
    time.sleep(random.uniform(a, b))

def human_type(el, text, min_delay=0.03, max_delay=0.12):
    try:
        el.clear()
    except Exception:
        pass
    for ch in text:
        try:
            el.send_keys(ch)
        except WebDriverException:
            break
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
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", el)
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

# ---------- undetected_chromedriver safe creation ----------
def _cleanup_udc_temp_files():
    """
    Attempt to remove likely conflicting files left by undetected_chromedriver's extraction
    so retries can proceed cleanly. This runs while holding the creation lock.
    """
    try:
        appdata = os.getenv("APPDATA") or os.path.expanduser("~")
        udc_base = os.path.join(appdata, "undetected_chromedriver")
        if not os.path.isdir(udc_base):
            return
        top_exe = os.path.join(udc_base, "undetected_chromedriver.exe")
        if os.path.exists(top_exe):
            try:
                os.remove(top_exe)
                print("[udc-cleanup] removed", top_exe)
            except Exception:
                pass
        chromedir = os.path.join(udc_base, "undetected", "chromedriver-win32")
        if os.path.isdir(chromedir):
            for fname in ("chromedriver.exe",):
                p = os.path.join(chromedir, fname)
                if os.path.exists(p):
                    try:
                        os.remove(p)
                        print("[udc-cleanup] removed", p)
                    except Exception:
                        pass
    except Exception as e:
        print("[udc-cleanup] failed:", e)

def safe_uc_chrome_create(opts, version_main, retries=5, tag=""):
    """
    Create uc.Chrome() safely with global serialization and retries.
    Returns driver on success or raises the last exception on failure.
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        with _uc_creation_lock:
            try:
                driver = uc.Chrome(options=opts, version_main=version_main, headless=False)
                return driver
            except FileExistsError as fe:
                print(f"{tag} [udc] FileExistsError on uc.Chrome(): attempt {attempt}/{retries} - cleaning udc temp files and retrying")
                _cleanup_udc_temp_files()
                last_exc = fe
            except Exception as e:
                print(f"{tag} [udc] uc.Chrome() failed on attempt {attempt}/{retries}: {e}")
                _cleanup_udc_temp_files()
                last_exc = e
        time.sleep(0.8 + random.random()*0.7)
    raise last_exc

# ---------- Page flow helpers with retries ----------
def close_cookie_strict(driver, wait_seconds=3):
    sel = "button.MuiButtonBase-root.MuiIconButton-root.MuiIconButton-sizeMedium.css-10snoxe"
    try:
        el = WebDriverWait(driver, wait_seconds).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
    except TimeoutException:
        return False

    try:
        try:
            img = el.find_element(By.TAG_NAME, "img")
            src = img.get_attribute("src") or ""
            if "close.svg" not in src and "close" not in src.lower():
                return False
        except NoSuchElementException:
            return False

        safe_action_click(driver, el)
        human_delay(0.35, 0.6)
        return True
    except Exception:
        return False

def find_and_click_create_account(driver, tag=""):
    """
    Robust search + click for the 'Create account' action. Multiple selectors / retries.
    Returns True on click success, False otherwise.
    """
    selectors = [
        (By.CSS_SELECTOR, "span[data-testid='test-button-createaccount']"),
        (By.XPATH, "//span[contains(normalize-space(.),'Create account') or @data-log-id='create-account']"),
        (By.XPATH, "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'create account')]"),
        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'create account')]"),
    ]
    for (by, sel) in selectors:
        try:
            el = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((by, sel)))
            safe_action_click(driver, el)
            human_delay(0.7, 1.2)
            return True
        except Exception:
            continue
    return False

def click_sign_in_then_createaccount_with_retries(driver, tag=""):
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            # try to open Sign in menu if present
            try:
                signbtn = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Sign in']")))
                safe_action_click(driver, signbtn)
                human_delay(0.6, 1.0)
            except Exception:
                # fallback: css class or ignore if not present
                try:
                    signbtn = driver.find_element(By.CSS_SELECTOR, "button.css-hrwkno")
                    safe_action_click(driver, signbtn)
                    human_delay(0.6, 1.0)
                except Exception:
                    pass

            if find_and_click_create_account(driver, tag=tag):
                return True

            # if not found, maybe page not fully interactive; refresh and retry
            print(f"{tag} create-account not found (attempt {attempt}/{RETRY_ATTEMPTS}), refreshing...")
            try:
                driver.refresh()
            except Exception:
                pass
            human_delay(1.0 + attempt*0.5, 1.8 + attempt*0.6)
        except Exception as e:
            print(f"{tag} exception in create-account attempts: {e}")
            try:
                driver.refresh()
            except Exception:
                pass
            human_delay(1.0, 2.0)
    return False

def ensure_checkbox_checked_before_agree_with_retries(driver, tag=""):
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        ok = ensure_checkbox_checked_before_agree(driver)
        if ok:
            return True
        print(f"{tag} checkbox check failed (attempt {attempt}/{RETRY_ATTEMPTS}), retrying...")
        try:
            driver.refresh()
        except Exception:
            pass
        human_delay(0.8 + attempt*0.4, 1.4 + attempt*0.6)
    return False

def click_agree_button_with_retries(driver, tag=""):
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        ok = click_agree_button(driver)
        if ok:
            return True
        print(f"{tag} agree click failed (attempt {attempt}/{RETRY_ATTEMPTS}), retrying (refresh)...")
        try:
            driver.refresh()
        except Exception:
            pass
        human_delay(0.8 + attempt*0.4, 1.6 + attempt*0.6)
    return False

# reuse earlier helper implementations (checkbox/agreement/fill)
def ensure_checkbox_checked_before_agree(driver):
    try:
        el_input = WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR, "input#all")))
    except TimeoutException:
        return True

    def is_checked(el):
        try:
            val = el.get_attribute("checked")
            if val is None:
                return el.is_selected()
            if str(val).lower() in ("true", "checked", "1") or val != "":
                return True
            return False
        except Exception:
            return False

    if is_checked(el_input):
        return True

    try:
        if el_input.is_displayed() and el_input.is_enabled():
            try:
                safe_action_click(driver, el_input)
                human_delay(0.12, 0.28)
            except Exception:
                pass
            if is_checked(el_input):
                return True
    except Exception:
        pass

    try:
        label = el_input.find_element(By.XPATH, "./ancestor::label[1]")
        if label:
            safe_action_click(driver, label)
            human_delay(0.12, 0.28)
            if is_checked(el_input):
                return True
    except Exception:
        pass

    try:
        span_candidates = driver.find_elements(By.XPATH, "//label//span[contains(@class,'MuiButtonBase-root') and contains(@class,'MuiCheckbox-root')]")
        for s in span_candidates:
            try:
                safe_action_click(driver, s)
                human_delay(0.12, 0.28)
                if is_checked(el_input):
                    return True
            except Exception:
                continue
    except Exception:
        pass

    try:
        driver.execute_script("""
            const cb = arguments[0];
            cb.checked = true;
            cb.setAttribute('checked','true');
            cb.dispatchEvent(new Event('input', { bubbles: true }));
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        """, el_input)
        human_delay(0.12, 0.28)
        if is_checked(el_input):
            return True
    except Exception:
        pass

    return is_checked(el_input)

def click_agree_button(driver):
    try:
        agree = WebDriverWait(driver, 12).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-log-id='agree']")))
        safe_action_click(driver, agree)
        human_delay(0.8, 1.2)
        return True
    except TimeoutException:
        try:
            agree = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Agree' or normalize-space()='I agree']")))
            safe_action_click(driver, agree)
            human_delay(0.8, 1.2)
            return True
        except TimeoutException:
            return False

def fill_signup_form(driver, email):
    try:
        account_input = wait_visible(driver, By.ID, "account", timeout=20)
        human_type(account_input, email)
    except TimeoutException:
        return False

    try:
        pw_input = wait_visible(driver, By.ID, "password", timeout=8)
        conf_input = wait_visible(driver, By.ID, "confirmPassword", timeout=8)
        human_type(pw_input, FIXED_PASSWORD)
        human_type(conf_input, FIXED_PASSWORD)
    except TimeoutException:
        return False

    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    try:
        fn_input = wait_visible(driver, By.ID, "firstName", timeout=8)
        ln_input = wait_visible(driver, By.ID, "lastName", timeout=8)
        human_type(fn_input, first_name)
        human_type(ln_input, last_name)
    except TimeoutException:
        return False

    day_value = str(random.randint(1, 28)).zfill(2)
    try:
        day_input = wait_visible(driver, By.ID, "day", timeout=6)
        human_type(day_input, day_value)
    except TimeoutException:
        return False

    month_value = random.choice([f"{i:02d}" for i in range(1,13)])
    try:
        month_select_el = wait_visible(driver, By.ID, "month", timeout=6)
        try:
            select = Select(month_select_el)
            select.select_by_value(month_value)
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", month_select_el, month_value)
    except TimeoutException:
        return False

    year_value = str(random.choice([2000,2001,2002,2003]))
    try:
        year_input = wait_visible(driver, By.ID, "year", timeout=6)
        human_type(year_input, year_value)
    except TimeoutException:
        return False

    human_delay(0.5, 0.9)
    return True

# ---------- Per-spot worker ----------
def create_chrome_options_windows(user_data_dir, profile_folder, extra_args=None):
    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument(f"--profile-directory={profile_folder}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    if extra_args:
        for a in extra_args:
            opts.add_argument(a)
    return opts

def wait_for_user_close(driver, poll_interval=2, max_wait=None, tag=""):
    """ Wait until user closes browser windows or driver becomes unreachable. """
    print(f"{tag} Waiting for manual browser/profile close (or auto-close timeout if set).")
    start = time.time()
    while True:
        if max_wait is not None and (time.time() - start) > max_wait:
            print(f"{tag} wait_for_user_close timed out after {max_wait}s.")
            return False
        try:
            handles = driver.window_handles
            if not handles:
                print(f"{tag} No browser windows detected: user closed browser.")
                return True
        except WebDriverException:
            print(f"{tag} WebDriverException while checking windows: browser probably closed.")
            return True
        time.sleep(poll_interval)

def worker_thread(spot: str, profile: str, email: str, auto_close_timeout: int, detach: bool, idx: int):
    """
    Opens Chrome for a single spot, performs signup steps with retries.
    On final failure of any critical step, takes a screenshot and WAITs for user to close the browser.
    """
    tag = f"[spot-{spot}]"
    base_user_data_dir = rf"C:\smsng_spot{spot}"
    profile_folder = f"profile{profile}"
    os.makedirs(base_user_data_dir, exist_ok=True)

    chrome_bin = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    alt = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_bin) and os.path.exists(alt):
        chrome_bin = alt

    opts = create_chrome_options_windows(base_user_data_dir, profile_folder)
    if os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin
        print(f"{tag} [#{idx}] Using Chrome binary: {chrome_bin}")
    else:
        print(f"{tag} [#{idx}] Chrome binary not found in common location, letting uc.Chrome decide")

    driver = None
    try:
        print(f"{tag} [#{idx}] Starting Chrome for {base_user_data_dir}")
        driver = safe_uc_chrome_create(opts, version_main=CHROME_MAJOR_VERSION, retries=6, tag=tag)
        driver.get(OKX_PHONE_URL)
        driver.implicitly_wait(1)
        human_delay(0.6, 1.2)

        # Try strict cookie close but ignore errors
        try:
            if close_cookie_strict(driver, wait_seconds=3):
                print(f"{tag} Closed strict cookie.")
        except Exception:
            pass

        # 1) Create account (robust)
        if not click_sign_in_then_createaccount_with_retries(driver, tag=tag):
            print(f"{tag} ERROR: create account step failed after retries.")
            if SCREENSHOT_ON_ERROR:
                try:
                    take_screenshot(driver, f"spot{spot}_create_account_error.png")
                except Exception:
                    pass
            # DO NOT quit: wait for user to close this profile (so it won't disappear)
            wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            return

        # 2) Ensure checkbox is checked BEFORE clicking Agree
        if not ensure_checkbox_checked_before_agree_with_retries(driver, tag=tag):
            print(f"{tag} ERROR: checkbox could not be checked after retries.")
            if SCREENSHOT_ON_ERROR:
                try:
                    take_screenshot(driver, f"spot{spot}_checkbox_fail.png")
                except Exception:
                    pass
            wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            return

        human_delay(0.4, 0.9)

        # 3) Click Agree
        if not click_agree_button_with_retries(driver, tag=tag):
            print(f"{tag} ERROR: Agree click failed after retries.")
            if SCREENSHOT_ON_ERROR:
                try:
                    take_screenshot(driver, f"spot{spot}_agree_fail.png")
                except Exception:
                    pass
            wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            return

        # 4) Fill the sign-up form (with small retries)
        filled = False
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            if fill_signup_form(driver, email):
                filled = True
                break
            print(f"{tag} form fill attempt {attempt}/{RETRY_ATTEMPTS} failed, refreshing and retrying...")
            try:
                driver.refresh()
            except Exception:
                pass
            human_delay(1.0 + attempt*0.6, 1.8 + attempt*0.8)
        if not filled:
            print(f"{tag} ERROR: Sign-up form fill failed after retries for email {email}.")
            if SCREENSHOT_ON_ERROR:
                try:
                    take_screenshot(driver, f"spot{spot}_fill_fail.png")
                except Exception:
                    pass
            wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            return

        print(f"{tag} SUCCESS: form filled with email {email} — waiting for user close or auto-close.")

        # Wait for user to close this browser instance or auto-close
        wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)

    except Exception as e:
        print(f"{tag} Unexpected error: {e}")
        traceback.print_exc()
        if SCREENSHOT_ON_ERROR and driver:
            try:
                take_screenshot(driver, f"spot{spot}_unexpected.png")
            except Exception:
                pass
        # On unexpected errors also wait so user can inspect the profile
        if driver:
            try:
                wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            except Exception:
                pass
    finally:
        if driver:
            try:
                if detach:
                    print(f"{tag} Detach requested; leaving browser running.")
                else:
                    try:
                        driver.quit()
                        print(f"{tag} driver.quit() completed.")
                    except Exception:
                        pass
            except Exception:
                pass

# ---------- Utilities for parsing input ----------
def load_emails_from_file(path: str) -> List[str]:
    emails = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    emails.append(ln)
    except Exception as e:
        print(f"[WARN] Could not load emails from {path}: {e}")
    return emails

def parse_csv_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(',') if x.strip()]

# ---------- Main ----------
def main():
    parser = argparse.ArgumentParser(description="Bulk Samsung signup (Windows-only) - wait on failures")
    parser.add_argument('--spots', help='Comma-separated spot ids e.g. 1,2,3', required=False)
    parser.add_argument('--profile', help='Single profile id used for all spots e.g. 1', required=False)
    parser.add_argument('--emails', help='Comma-separated emails OR path to file with emails', required=False)
    parser.add_argument('--auto-close-timeout', help='Seconds to wait after filling form before auto-closing (default: wait for manual close)', type=int, required=False)
    parser.add_argument('--detach', help='Leave browsers running on exit', action='store_true')
    args = parser.parse_args()

    spots_input = args.spots or input("Enter spot ids (comma-separated, e.g. 1,2,3): ")
    profile_input = args.profile or input("Enter single profile id to use for all spots (e.g. 1): ")
    emails_input = args.emails or input("Enter emails (comma-separated) OR path to file: ")

    spots = parse_csv_list(spots_input)
    if not spots:
        print("[ERROR] No spots supplied.")
        return

    profile = profile_input.strip() or '1'

    emails = []
    if os.path.exists(emails_input):
        emails = load_emails_from_file(emails_input)
    else:
        emails = parse_csv_list(emails_input)

    if not emails:
        print("[ERROR] No emails supplied.")
        return

    assigned_emails = []
    for i, s in enumerate(spots):
        assigned_emails.append(emails[i % len(emails)])

    print("\nConfiguration:")
    print(f"  Spots: {spots}")
    print(f"  Profile used for all: profile{profile}")
    print(f"  Emails assigned: {assigned_emails}")
    print(f"  Auto-close timeout: {args.auto_close_timeout}")
    print(f"  Detach: {args.detach}\n")

    threads = []
    for idx, spot in enumerate(spots, start=1):
        email = assigned_emails[idx-1]
        t = threading.Thread(target=worker_thread, args=(spot, profile, email, args.auto_close_timeout, args.detach, idx), daemon=False)
        threads.append(t)
        t.start()
        # stagger thread starts slightly
        time.sleep(1.2 + random.random()*0.8)

    print("[INFO] All worker threads started. Waiting for them to finish... (CTRL+C to abort)")

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("[WARN] KeyboardInterrupt received: main thread exiting. Worker threads may leave browsers open if detach=True is used.")

    print("[INFO] Bulk run completed.")

if __name__ == '__main__':
    main()
