#!/usr/bin/env python3
"""
multi_account_create.py

Windows-only bulk Samsung signup script (human-like) using undetected_chromedriver.

Key behavior (changes compared to earlier version):
 - For each (spot, profile) the script fetches an email row from misc/email_fetcher.get_email_for_profile.
   The row must contain at least `email` and `email_psw`.
 - After filling the Samsung signup form the worker polls the mailbox by calling:
       from mail import fetch_codes_for_address
       codes = fetch_codes_for_address(email, password=email_psw, api_base=..., api_key=...)
   It uses the returned first code (if any) to fill the OTP input (#otp) and click Next.
 - CLI exposes options to override mail API base/key, verification timeout/poll interval, detach, auto-close, etc.
 - Preserves previous robustness: retries, screenshot-on-error, wait-for-user-close, leaving browser open when detach=True.

Usage examples:
  python multi_account_create.py --spots 1,2,3 --profile 1
  python multi_account_create.py --spots 1 --profile 1 --verification-timeout 180 --verification-poll 4
  python multi_account_create.py --spots 1,2 --profile 1 --detach --auto-close-timeout 60

Requirements:
 - mail.py must expose fetch_codes_for_address(address, password, api_base=None, api_key=None, ...)
 - misc/email_fetcher.py must expose get_email_for_profile(spot_id, profile_id) and return dict with email, email_psw.

Drop this file in your project and run.
"""
from __future__ import annotations
import os
import sys
import time
import random
import argparse
import threading
import ssl
import certifi
import traceback
from typing import List, Optional, Dict, Any

ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# Import the simple fetch function from your mail.py
try:
    from mail import fetch_codes_for_address
except Exception:
    # try to load from same directory
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mail import fetch_codes_for_address  # type: ignore

# Import DB email fetcher
try:
    from misc.email_fetcher import get_email_for_profile
except Exception:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "misc"))
    from email_fetcher import get_email_for_profile  # type: ignore

# ---------------- Config ----------------
OKX_PHONE_URL = "https://v3.account.samsung.com/dashboard/security/phone"
CHROME_MAJOR_VERSION = 141
FIXED_PASSWORD = "@Smsng#860"
DEFAULT_WAIT_SECONDS = 25
SCREENSHOT_ON_ERROR = True
RETRY_ATTEMPTS = 3
# ----------------------------------------

FIRST_NAMES = ["Adam", "Bilal", "Omar", "Usman", "Aamir", "Sara", "Ayesha", "Nadia", "Zara", "Hassan", "Ali", "Ibrahim"]
LAST_NAMES  = ["Khan", "Ahmed", "Hussain", "Malik", "Farooq", "Abbasi", "Saeed", "Raza", "Iqbal", "Shah"]

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

# ---------- uc.Chrome creation ----------
def _cleanup_udc_temp_files():
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

# ---------- Page helpers ----------
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
            try:
                signbtn = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Sign in']")))
                safe_action_click(driver, signbtn)
                human_delay(0.6, 1.0)
            except Exception:
                try:
                    signbtn = driver.find_element(By.CSS_SELECTOR, "button.css-hrwkno")
                    safe_action_click(driver, signbtn)
                    human_delay(0.6, 1.0)
                except Exception:
                    pass

            if find_and_click_create_account(driver, tag=tag):
                return True

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

# ---------- OTP entry ----------
def enter_code_and_click_next(driver, code: str, tag: str) -> bool:
    try:
        otp_input = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.ID, "otp")))
        human_type(otp_input, code)
        human_delay(0.15, 0.4)
    except TimeoutException:
        print(f"{tag} OTP input not visible yet.")
        return False
    except Exception as e:
        print(f"{tag} error typing OTP: {e}")
        return False

    selectors = [
        (By.CSS_SELECTOR, "button[data-testid='test-button-next']"),
        (By.XPATH, "//button[normalize-space()='Next' or contains(., 'Next')]"),
        (By.CSS_SELECTOR, "button[type='submit']")
    ]
    for (by, sel) in selectors:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, sel)))
            safe_action_click(driver, btn)
            human_delay(0.5, 1.0)
            print(f"{tag} OTP entered and Next clicked.")
            return True
        except Exception:
            continue
    print(f"{tag} Could not find/click the Next button after entering OTP.")
    return False

# ---------- Worker and polling ----------
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

def poll_mail_for_verification_code_simple(email: str, email_psw: str, api_base: Optional[str], api_key: Optional[str], timeout: int, poll_interval: float, tag: str) -> Optional[str]:
    """
    Poll mailbox by calling mail.fetch_codes_for_address(email, password=email_psw, api_base=..., api_key=...)
    Return first code string or None if timeout.
    """
    start = time.time()
    print(f"{tag} Polling mailbox for {email} up to {timeout}s (poll {poll_interval}s)...")
    while True:
        try:
            codes = fetch_codes_for_address(address=email, password=email_psw)
        except Exception as e:
            # log and continue until timeout
            print(f"{tag} Mail fetch exception: {e}")
            codes = []
        if codes:
            print(f"{tag} Mailbox returned codes: {codes}")
            return codes[0]
        if timeout is not None and (time.time() - start) > timeout:
            print(f"{tag} Verification polling timed out after {timeout} seconds for {email}.")
            return None
        time.sleep(poll_interval)

def worker_thread(spot: str, profile: str, email_row: Dict[str, Any], auto_close_timeout: int, detach: bool, idx: int,
                  mail_api_base: Optional[str], mail_api_key: Optional[str], verification_timeout: int, verification_poll: float):
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
    email = email_row.get("email")
    email_psw = email_row.get("email_psw") or os.getenv("SMTP_DEV_PASSWORD", "")
    try:
        print(f"{tag} [#{idx}] Starting Chrome for {base_user_data_dir} (email={email})")
        driver = safe_uc_chrome_create(opts, version_main=CHROME_MAJOR_VERSION, retries=6, tag=tag)
        driver.get(OKX_PHONE_URL)
        driver.implicitly_wait(1)
        human_delay(0.6, 1.2)

        try:
            if close_cookie_strict(driver, wait_seconds=3):
                print(f"{tag} Closed strict cookie.")
        except Exception:
            pass

        # 1) Create account
        if not click_sign_in_then_createaccount_with_retries(driver, tag=tag):
            print(f"{tag} ERROR: create account step failed after retries.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, f"spot{spot}_create_account_error.png")
            wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            return

        # 2) Ensure checkbox
        if not ensure_checkbox_checked_before_agree_with_retries(driver, tag=tag):
            print(f"{tag} ERROR: checkbox could not be checked after retries.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, f"spot{spot}_checkbox_fail.png")
            wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            return

        human_delay(0.4, 0.9)

        # 3) Click Agree
        if not click_agree_button_with_retries(driver, tag=tag):
            print(f"{tag} ERROR: Agree click failed after retries.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, f"spot{spot}_agree_fail.png")
            wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            return

        # 4) Fill form
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
                take_screenshot(driver, f"spot{spot}_fill_fail.png")
            wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)
            return

        print(f"{tag} SUCCESS: form filled with email {email} — polling mailbox for verification code now.")

        # Poll mail using the simple fetch function from mail.py
        code = poll_mail_for_verification_code_simple(email, email_psw, api_base=mail_api_base or None, api_key=mail_api_key or None, timeout=verification_timeout, poll_interval=verification_poll, tag=tag)
        if code:
            success = False
            for attempt in range(1, 8):
                try:
                    if enter_code_and_click_next(driver, code, tag=tag):
                        success = True
                        break
                except Exception as e:
                    print(f"{tag} Exception while entering code: {e}")
                human_delay(1.5 + attempt * 0.8, 2.2 + attempt * 0.9)
            if not success:
                print(f"{tag} Warning: code found ({code}) but could not be entered/clicked in the page.")
                if SCREENSHOT_ON_ERROR:
                    take_screenshot(driver, f"spot{spot}_code_entry_fail.png")
        else:
            print(f"{tag} No verification code received within timeout ({verification_timeout}s) for {email}.")

        print(f"{tag} Worker done. Waiting for user close or auto-close.")
        wait_for_user_close(driver, poll_interval=2, max_wait=auto_close_timeout, tag=tag)

    except Exception as e:
        print(f"{tag} Unexpected error: {e}")
        traceback.print_exc()
        if SCREENSHOT_ON_ERROR and driver:
            try:
                take_screenshot(driver, f"spot{spot}_unexpected.png")
            except Exception:
                pass
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

# ---------- Utilities ----------
def parse_csv_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(',') if x.strip()]

# ---------- Main ----------
def main():
    parser = argparse.ArgumentParser(description="Bulk Samsung signup (Windows-only) - fetch emails from misc/email_fetcher.py and OTP via mail.fetch_codes_for_address")
    parser.add_argument('--spots', help='Comma-separated spot ids e.g. 1,2,3', required=False)
    parser.add_argument('--profile', help='Single profile id used for all spots e.g. 1', required=False)
    parser.add_argument('--emails', help='(optional) override DB fetch with comma-separated emails', required=False)
    parser.add_argument('--auto-close-timeout', help='Seconds to wait after filling form before auto-closing (default: wait for manual close)', type=int, required=False)
    parser.add_argument('--detach', help='Leave browsers running on exit', action='store_true')
    parser.add_argument('--mail-api-base', help='SMTP.dev API base URL (overrides SMTP_DEV_BASE env)', required=False)
    parser.add_argument('--mail-api-key', help='SMTP.dev API key (overrides SMTP_DEV_API_KEY env)', required=False)
    parser.add_argument('--verification-timeout', help='Seconds to wait for verification code (default 300)', type=int, default=300)
    parser.add_argument('--verification-poll', help='Seconds between mailbox polls (default 5)', type=float, default=5.0)
    args = parser.parse_args()

    spots_input = args.spots or input("Enter spot ids (comma-separated, e.g. 1,2,3): ")
    profile_input = args.profile or input("Enter single profile id to use for all spots (e.g. 1): ")

    spots = parse_csv_list(spots_input)
    if not spots:
        print("[ERROR] No spots supplied.")
        return

    profile = profile_input.strip() or '1'

    # fetch rows (either override by --emails or use DB)
    fetched_rows: List[Dict[str, Any]] = []
    if args.emails:
        emails_list = parse_csv_list(args.emails)
        for i, s in enumerate(spots):
            fetched_rows.append({"email": emails_list[i % len(emails_list)], "email_psw": os.getenv("SMTP_DEV_PASSWORD", "")})
    else:
        for s in spots:
            try:
                row = get_email_for_profile(int(s), int(profile))
            except Exception as e:
                print(f"[WARN] DB fetch error for spot {s} profile {profile}: {e}")
                row = None
            if not row:
                print(f"[ERROR] No DB row for spot {s} profile {profile}. Skipping this spot.")
                fetched_rows.append({"email": None, "email_psw": None})
            else:
                fetched_rows.append(row)

    assigned_emails = [r.get("email") for r in fetched_rows]
    print("\nConfiguration:")
    print(f"  Spots: {spots}")
    print(f"  Profile used for all: profile{profile}")
    print(f"  Emails fetched/assigned: {assigned_emails}")
    print(f"  Auto-close timeout: {args.auto_close_timeout}")
    print(f"  Detach: {args.detach}")
    print(f"  Mail API base: {args.mail_api_base or os.getenv('SMTP_DEV_BASE') or 'DEFAULT'}")
    print(f"  Mail API key: {'(provided)' if args.mail_api_key or os.getenv('SMTP_DEV_API_KEY') else '(NOT SET)'}")
    print(f"  Verification timeout: {args.verification_timeout}s, poll every {args.verification_poll}s\n")

    threads = []
    for idx, spot in enumerate(spots, start=1):
        email_row = fetched_rows[idx-1]
        email = email_row.get("email")
        if not email:
            print(f"[WARN] skipping spot {spot} because no email was fetched.")
            continue
        t = threading.Thread(
            target=worker_thread,
            args=(spot, profile, email_row, args.auto_close_timeout, args.detach, idx,
                  args.mail_api_base, args.mail_api_key,
                  args.verification_timeout, args.verification_poll),
            daemon=False
        )
        threads.append(t)
        t.start()
        time.sleep(1.2 + random.random()*0.8)

    if not threads:
        print("[ERROR] No worker threads started (no valid emails). Exiting.")
        return

    print("[INFO] All worker threads started. Waiting for them to finish... (CTRL+C to abort)")

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("[WARN] KeyboardInterrupt received: main thread exiting. Worker threads may leave browsers open if detach=True is used.")

    print("[INFO] Bulk run completed.")

if __name__ == '__main__':
    main()
