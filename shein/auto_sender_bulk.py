#!/usr/bin/env python3
"""
Shein phone verification flow — temporary Chrome profiles, 5 numbers per profile.

Changes from original:
 - Script asks only for `range_id` at start (selects numbers from that range).
 - Creates a temporary Chrome profile directory for each batch.
 - Each temporary profile will attempt up to `MAX_NUMBERS_PER_PROFILE` numbers (default 5).
 - After the profile has tried that many numbers it is destroyed and a new temporary profile is created.
 - On any result (success / limit / invalid / unknown) the number's comment is updated via num_fetcher.update_login_cmnt,
   numbers are freed when appropriate, and the script proceeds to the next number until the batch is exhausted.
 - Conservative detection and dialog-closing logic preserved.
"""

import os
import sys
import time
import ssl
import certifi
import re
import random
import tempfile
import shutil
from pathlib import Path

ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

# Make misc importable
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
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
)

import num_fetcher

# ----------------- CONFIG -----------------
SHEIN_LOGIN_URL = "https://www.shein.co.uk/user/auth/login?direction=nav&from=navTop"
CHROME_MAJOR_VERSION = 144
DEFAULT_WAIT_SECONDS = 20
SCREENSHOT_ON_ERROR = True
RESERVE_TRIES = 4
HUMAN_MIN_DELAY = 0.12
HUMAN_MAX_DELAY = 0.35
ACTION_MIN_DELAY = 0.5
ACTION_MAX_DELAY = 1.4
RECHECK_DELAY = 0.6
MAX_UNKNOWN_RETRIES = 2
MAX_NUMBERS_PER_PROFILE = 5  # new: attempt this many numbers per temporary profile
HEADLESS = True  # change to False if you want visible browser for debugging
# -----------------------------------------


def human_sleep(min_s=ACTION_MIN_DELAY, max_s=ACTION_MAX_DELAY):
    s = random.uniform(min_s, max_s)
    time.sleep(s)


def type_like_human(element, text):
    try:
        element.clear()
    except Exception:
        pass
    human_sleep(0.08, 0.18)
    for ch in str(text):
        element.send_keys(ch)
        time.sleep(random.uniform(HUMAN_MIN_DELAY, HUMAN_MAX_DELAY))
    element.send_keys(Keys.TAB)


def safe_click(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        human_sleep(0.08, 0.18)
        element.click()
        return True
    except (ElementClickInterceptedException, ElementNotInteractableException, StaleElementReferenceException):
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


def take_screenshot(driver, name):
    try:
        driver.save_screenshot(name)
        print(f"[+] Screenshot saved: {name}")
    except Exception:
        pass


def find_phone_input(driver, wait_seconds=DEFAULT_WAIT_SECONDS):
    wait = WebDriverWait(driver, wait_seconds)
    return wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//input[contains(@class,'sui-input__inner') and (not(@type) or @type='text' or @type='tel')]")
        )
    )


def enter_phone_only(driver, phone):
    try:
        inp = find_phone_input(driver)
        type_like_human(inp, phone)
        print(f"[+] Phone entered: {phone}")
        return True
    except TimeoutException:
        print("[ERROR] Phone input not found")
        return False


def clear_phone_input_field(driver):
    try:
        driver.execute_script(
            "(function(){var el=document.querySelector('input.sui-input__inner'); if(el){ el.focus(); el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }})();"
        )
        human_sleep(0.08, 0.18)
    except Exception:
        pass


def select_country_after_phone(driver, number_row):
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    try:
        opener = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'page-login__phoneArea')]//p[1]"))
        )
        safe_click(driver, opener)
        human_sleep(0.3, 0.8)
    except TimeoutException:
        print("[ERROR] Country dropdown opener not found")
        return False

    country_name = (number_row.get("country_name") or "").strip()
    country_code = (number_row.get("country_code") or "").replace("+", "").strip()

    try:
        options_parent = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'options')]"))
        )
    except TimeoutException:
        options_parent = None

    options = []
    if options_parent:
        options = options_parent.find_elements(By.XPATH, ".//li")
    if not options:
        options = driver.find_elements(By.XPATH, "//div[contains(@class,'options')]//li")

    target = None
    for li in options:
        try:
            text = (li.text or "").strip()
            if not text:
                continue
            lname = text.lower()
            if country_name and country_name.lower() in lname:
                target = li
                break
            if country_code and country_code in lname:
                target = li
                break
        except StaleElementReferenceException:
            continue

    if not target and options:
        target = options[0]

    if not target:
        print("[ERROR] No country options found")
        return False

    if safe_click(driver, target):
        human_sleep(0.3, 0.8)
        print(f"[+] Country selected: {target.text.strip()}")
        return True

    print("[ERROR] Failed to click target country")
    return False


def click_continue_sms(driver):
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    try:
        btn = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(., 'Continue') and contains(., 'SMS')] | //button[.//span[normalize-space()='Continue with SMS']] | //button[contains(., 'Send') and contains(., 'SMS')]")
            )
        )
        safe_click(driver, btn)
        human_sleep(0.4, 1.0)
        print("[+] Continue with SMS clicked")
        return True
    except TimeoutException:
        try:
            btn2 = driver.find_element(By.XPATH, "//button[.//span[normalize-space()='Register']]")
            safe_click(driver, btn2)
            human_sleep(0.4, 1.0)
            print("[+] Register button clicked (fallback)")
            return True
        except Exception:
            print("[ERROR] Continue with SMS/Register button not found")
            return False


def detect_case_strict(conn, driver, phone):
    """Returns: 'invalid', 'success', 'limit', or 'unknown'.
    Also updates DB comments for determinate results.
    """
    human_sleep(RECHECK_DELAY * 0.8, RECHECK_DELAY * 1.4)

    # 1) inline input-specific errors
    try:
        wrappers = driver.find_elements(By.XPATH, "//div[contains(@class,'input_filed-wrapper') or contains(@class,'page__login_input-filed')]")
        for w in wrappers:
            try:
                w.find_element(By.XPATH, ".//input[contains(@class,'sui-input__inner')]")
            except Exception:
                continue
            try:
                err = w.find_element(By.XPATH, ".//p[contains(@class,'error-tip')]")
                txt = (err.text or "").strip()
                if not txt:
                    continue
                low = txt.lower()
                if 'please input the correct phone number' in low or 'please input the correct' in low or 'incorrect phone' in low or 'invalid phone' in low:
                    num_fetcher.update_login_cmnt(conn, phone, 'Invalid Number')
                    return 'invalid'
            except Exception:
                pass
    except Exception:
        pass

    # 2) verification code panel / code input visible
    try:
        code_panels = driver.find_elements(By.XPATH, "//div[contains(@class,'page__login-newUI-code') or contains(@class,'page__login-code-number')]")
        for cp in code_panels:
            text_nodes = cp.find_elements(By.XPATH, ".//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'verification code is sent')]")
            inputs = cp.find_elements(By.XPATH, ".//input[@maxlength='6' or @type='password' or @type='text']")
            visible_inputs = [i for i in inputs if i.is_displayed()]
            if text_nodes or visible_inputs:
                has_code_text = any((n.text or '').strip() for n in text_nodes)
                has_visible_code_input = any(True for _ in visible_inputs)
                if has_code_text or has_visible_code_input:
                    num_fetcher.update_login_cmnt(conn, phone, 'Successfully Sent')
                    return 'success'
    except Exception:
        pass

    # 3) dialog with 'Verification code send error'
    try:
        dialogs = driver.find_elements(By.XPATH, "//div[contains(@class,'sui-dialog__body') or contains(@class,'sui-dialog__wrapper')]")
        for d in dialogs:
            try:
                p_nodes = d.find_elements(By.XPATH, ".//p | .//h2 | .//div")
                for p in p_nodes:
                    txt = (p.text or "").strip()
                    if not txt:
                        continue
                    if 'verification code send error' in txt.lower():
                        num_fetcher.update_login_cmnt(conn, phone, 'Limit sending error')
                        return 'limit'
            except Exception:
                continue
    except Exception:
        pass

    return 'unknown'


def click_close_dialog_button(driver):
    try:
        wait = WebDriverWait(driver, 4)
        close_el = None
        try:
            close_el = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(@class,'sui-dialog__closebtn') and (@aria-label='close' or @role='button')]"))
            )
        except TimeoutException:
            try:
                close_el = driver.find_element(By.XPATH, "//span[contains(@class,'sui-dialog__closebtn') and (@aria-label='close' or @role='button')]")
            except Exception:
                close_el = None

        if close_el:
            if safe_click(driver, close_el):
                human_sleep(0.25, 0.6)
                print("[+] Dialog close button clicked")
                return True
            else:
                try:
                    driver.execute_script("var el = document.querySelector('span.sui-dialog__closebtn[aria-label=\"close\"]'); if(el){ el.click(); }")
                    human_sleep(0.25, 0.6)
                    print("[+] Dialog close clicked by JS")
                    return True
                except Exception:
                    print("[WARN] Couldn't click dialog close button (JS failed)")
                    return False
        else:
            try:
                driver.execute_script("""
                    (function(){
                        var el = document.querySelector('.sui-dialog__wrapper') || document.querySelector('.sui-dialog__body');
                        if(el && el.parentNode){ el.parentNode.removeChild(el); }
                        var overlay = document.querySelector('.sui-dialog__mask');
                        if(overlay && overlay.parentNode){ overlay.parentNode.removeChild(overlay); }
                    })();
                """)
                human_sleep(0.25, 0.6)
                print("[+] Dialog wrapper/overlay removed by JS fallback")
                return True
            except Exception:
                print("[WARN] Couldn't remove dialog via JS fallback")
                return False

    except Exception as e:
        print(f"[WARN] Exception while trying to close dialog: {e}")
        return False


def create_temp_profile_dir():
    tmpdir = tempfile.mkdtemp(prefix="sms_tmp_profile_")
    return tmpdir


def destroy_profile_dir(path):
    try:
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"[+] Temp profile dir removed: {path}")
    except Exception as e:
        print(f"[WARN] Failed to remove profile dir {path}: {e}")


def make_driver_with_profile(profile_dir):
    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    if HEADLESS:
        # headless with user-data-dir can be flaky, but keep as configurable option
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
    driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION)
    return driver


def main():
    print("=== SHEIN PHONE FLOW — temporary profiles, 5 numbers per profile ===")

    # Only ask for range_id at start as requested
    range_id = input("Enter range_id: ").strip()
    if not range_id:
        print("Range id required. Exiting.")
        return

    user_id = num_fetcher.read_user_id_from_file(num_fetcher.USER_FILE)
    conn = num_fetcher.get_db_connection()

    try:
        # main loop: create temp profile, process up to MAX_NUMBERS_PER_PROFILE numbers, destroy profile, repeat
        while True:
            temp_profile_dir = create_temp_profile_dir()
            driver = None
            try:
                print(f"\n[+] Created temp profile dir: {temp_profile_dir}")
                try:
                    driver = make_driver_with_profile(temp_profile_dir)
                except Exception as e:
                    print(f"[FATAL] Could not start Chrome with profile {temp_profile_dir}: {e}")
                    destroy_profile_dir(temp_profile_dir)
                    # if cannot start browser, stop entire process
                    break

                # open Shein login page once for this profile
                try:
                    driver.get(SHEIN_LOGIN_URL)
                    human_sleep(0.8, 1.6)
                except Exception as e:
                    print(f"[WARN] Could not open login page initially: {e}")

                # For each profile we attempt up to MAX_NUMBERS_PER_PROFILE numbers
                attempted_in_this_profile = 0
                while attempted_in_this_profile < MAX_NUMBERS_PER_PROFILE:
                    number_row = None
                    phone = None
                    reserved = False

                    # Reserve a number (with retries)
                    for _ in range(RESERVE_TRIES):
                        number_row = num_fetcher.get_random_number(conn, range_id, user_id)
                        if not number_row:
                            break
                        phone = str(number_row["number"])
                        if num_fetcher.reserve_number(conn, phone):
                            reserved = True
                            break
                        else:
                            phone = None
                            number_row = None

                    if not reserved:
                        print("[ERROR] No number available or reserve failed — finishing overall.")
                        # no numbers available: break both loops and finish
                        attempted_in_this_profile = MAX_NUMBERS_PER_PROFILE
                        break

                    attempted_in_this_profile += 1
                    print(f"\n--- TempProfileAttempt #{attempted_in_this_profile} (phone: {phone}) ---")

                    unknown_tries = 0
                    try:
                        # ensure input is clear
                        clear_phone_input_field(driver)
                        human_sleep(0.2, 0.6)

                        if not enter_phone_only(driver, phone):
                            raise Exception("Phone input not found or not interactable")

                        human_sleep(0.25, 0.6)

                        # select country (best-effort)
                        if not select_country_after_phone(driver, number_row):
                            print("[WARN] Country selection fallback — proceeding")

                        human_sleep(0.3, 0.7)

                        if not click_continue_sms(driver):
                            raise Exception("Continue/Register button not found")

                        # conservative detection
                        result = detect_case_strict(conn, driver, phone)

                        if result == 'success':
                            print("[+] Successfully sent (record updated). Will close dialog and continue with next number in this profile.")
                            try:
                                # try to close dialog so UI is clean for the next input
                                click_close_dialog_button(driver)
                            except Exception:
                                pass
                            # free number as before (decrement limit / return)
                            try:
                                num_fetcher.free_number(conn, phone)
                            except Exception:
                                pass
                            # clear input and continue to next number
                            clear_phone_input_field(driver)
                            human_sleep(0.4, 0.9)
                            continue

                        elif result == 'invalid':
                            print("[*] Invalid number (DB updated). Freeing and trying next number.")
                            try:
                                num_fetcher.free_number(conn, phone)
                            except Exception:
                                pass
                            clear_phone_input_field(driver)
                            human_sleep(0.4, 0.9)
                            continue

                        elif result == 'limit':
                            print("[*] Limit sending error (DB updated). Will close dialog and try next number.")
                            try:
                                click_close_dialog_button(driver)
                            except Exception:
                                pass
                            try:
                                num_fetcher.free_number(conn, phone)
                            except Exception:
                                pass
                            clear_phone_input_field(driver)
                            human_sleep(0.4, 0.9)
                            continue

                        else:
                            # unknown -> retry limited times
                            unknown_tries += 1
                            print(f"[?] Unknown result (attempt {unknown_tries}). Retrying small number of times...")
                            if SCREENSHOT_ON_ERROR:
                                take_screenshot(driver, f"unknown_temp_{temp_profile_dir.replace(os.sep,'_')}_try{unknown_tries}.png")
                            if unknown_tries > MAX_UNKNOWN_RETRIES:
                                print("[WARN] Giving up on this number after unknown retries. Freeing and continuing.")
                                try:
                                    num_fetcher.free_number(conn, phone)
                                except Exception:
                                    pass
                                clear_phone_input_field(driver)
                                human_sleep(0.4, 0.9)
                                continue
                            else:
                                human_sleep(1.0, 2.0)
                                # re-run detection once after pause
                                result2 = detect_case_strict(conn, driver, phone)
                                if result2 in ('success', 'invalid', 'limit'):
                                    # we rely on detect_case_strict to update DB already
                                    if result2 == 'success':
                                        try:
                                            click_close_dialog_button(driver)
                                        except Exception:
                                            pass
                                        try:
                                            num_fetcher.free_number(conn, phone)
                                        except Exception:
                                            pass
                                    else:
                                        try:
                                            num_fetcher.free_number(conn, phone)
                                        except Exception:
                                            pass
                                    clear_phone_input_field(driver)
                                    human_sleep(0.4, 0.9)
                                    continue
                                else:
                                    # treat as failed after retry
                                    try:
                                        num_fetcher.free_number(conn, phone)
                                    except Exception:
                                        pass
                                    clear_phone_input_field(driver)
                                    human_sleep(0.4, 0.9)
                                    continue

                    except Exception as e:
                        print(f"[ERROR] Exception during attempt for phone {phone}: {e}")
                        if SCREENSHOT_ON_ERROR and driver:
                            take_screenshot(driver, f"attempt_error_temp_{attempted_in_this_profile}.png")
                        # ensure number freed on unexpected exception
                        if reserved and phone:
                            try:
                                num_fetcher.free_number(conn, phone)
                            except Exception:
                                pass
                        clear_phone_input_field(driver)
                        human_sleep(0.8, 1.6)
                        continue

                # end while attempted_in_this_profile

            finally:
                # ensure driver closed and profile dir destroyed
                if driver:
                    try:
                        driver.quit()
                        human_sleep(0.2, 0.6)
                    except Exception:
                        pass
                # destroy the temp profile dir
                destroy_profile_dir(temp_profile_dir)

            # After destroying profile, we'll loop back and create another temp profile unless numbers exhausted
            # Quick check: ask DB for one random number to see if any left (without reserving)
            try:
                test_row = num_fetcher.get_random_number(conn, range_id, user_id)
                if not test_row:
                    print("[+] No more numbers available in the selected range. Exiting.")
                    break
                else:
                    # nothing to do: loop will create new profile and continue
                    continue
            except Exception:
                # On DB error, exit to be safe
                print("[WARN] DB check failed after profile batch; exiting.")
                break

    finally:
        try:
            conn.close()
        except Exception:
            pass

    print("\nDONE.")


if __name__ == '__main__':
    main()