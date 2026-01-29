#!/usr/bin/env python3
"""
Shein phone verification flow — rewritten for accurate detection and human-like behaviour.

aFeatures:a
 - Enters phone by simulating human typing (per-character send_keys with small random delays)
 - Uses randomized, configurable delays between actions to look more human
 - Robust detection logic for 3 cases:
     CASE 1: inline error under the phone input -> login_cmnt = 'Invalid Number'
     CASE 2: verification code panel with code input visible -> login_cmnt = 'Successfully Sent'
     CASE 3: dialog titled 'Verification code send error' -> login_cmnt = 'Limit sending error'
 - Conservative detection to avoid false positives: checks element hierarchy and visible text, waits and re-checks, and uses negative-probing (ensure element presence and visibility)
 - Re-uses a single browser/profile for multiple number attempts; only moves to next profile after CASE 2 (success)
 - Clears the phone input reliably between attempts
 - Uses `num_fetcher.update_login_cmnt(conn, number, comment)` to write outcomes

Notes:
 - Keep `config.py` with DB credentials as before.
 - Install dependencies: undetected-chromedriver, selenium, pymysql, certifi
"""

import os
import sys
import time
import ssl
import certifi
import re
import random
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
HUMAN_MIN_DELAY = 0.12   # minimal per-character typing delay
HUMAN_MAX_DELAY = 0.35   # maximal per-character typing delay
ACTION_MIN_DELAY = 0.5
ACTION_MAX_DELAY = 1.4
RECHECK_DELAY = 0.6       # small wait before re-checking DOM state
MAX_UNKNOWN_RETRIES = 2   # when unknown state occurs, retry a couple times
# -----------------------------------------


def human_sleep(min_s=ACTION_MIN_DELAY, max_s=ACTION_MAX_DELAY):
    """Sleep a small randomized interval to mimic human behavior."""
    s = random.uniform(min_s, max_s)
    time.sleep(s)


def type_like_human(element, text):
    """Type into an input element one char at a time with random delays.
    Uses element.send_keys for each character to allow JS frameworks to catch events.
    """
    try:
        element.clear()
    except Exception:
        pass
    human_sleep(0.08, 0.18)
    for ch in str(text):
        element.send_keys(ch)
        time.sleep(random.uniform(HUMAN_MIN_DELAY, HUMAN_MAX_DELAY))
    # final blur/tab to trigger change events
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
    """Find the phone input element. This is conservative and retries a few times."""
    wait = WebDriverWait(driver, wait_seconds)
    # broad selector but we verify proximity to phone area later
    return wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//input[contains(@class,'sui-input__inner') and (not(@type) or @type='text' or @type='tel')]")
        )
    )


def enter_phone_only(driver, phone):
    try:
        inp = find_phone_input(driver)
        # type slowly (human-like)
        type_like_human(inp, phone)
        print(f"[+] Phone entered: {phone}")
        return True
    except TimeoutException:
        print("[ERROR] Phone input not found")
        return False


def clear_phone_input_field(driver):
    """Clear using JS to ensure frameworks notice the change + dispatch input events."""
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
        # better: click the phone area opener (p tag inside phone area)
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

    # wait for options container to appear
    try:
        options_parent = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'options')]"))
        )
    except TimeoutException:
        # sometimes option list is rendered elsewhere; fallback to searching anywhere
        options_parent = None

    options = []
    if options_parent:
        options = options_parent.find_elements(By.XPATH, ".//li")
    if not options:
        options = driver.find_elements(By.XPATH, "//div[contains(@class,'options')]//li")

    # normalize for comparisons
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
        # button text might vary; use contains 'Continue' + 'SMS' or exact label
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
        # there is a chance the site shows Register instead of Continue; try clicking Register
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
    """More conservative detection with repeated checks and visibility tests.

    Returns: 'invalid', 'success', 'limit', or 'unknown'
    """
    # wait a short while to allow DOM updates
    human_sleep(RECHECK_DELAY * 0.8, RECHECK_DELAY * 1.4)

    # 1) look for an input-field-specific error: the <p class='error-tip'> that sits under input wrapper
    try:
        # find the input wrapper containing our visible input and then find its error child
        wrappers = driver.find_elements(By.XPATH, "//div[contains(@class,'input_filed-wrapper') or contains(@class,'page__login_input-filed')]")
        for w in wrappers:
            try:
                # look for the input inside this wrapper
                inp = w.find_element(By.XPATH, ".//input[contains(@class,'sui-input__inner')]")
            except Exception:
                continue
            # if this wrapper has an error-tip with relevant text -> invalid number
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

    # 2) look for the verification code panel: usually contains 'verification code is sent' and an input of maxlength=6
    try:
        # check for a code-area with the text or visible code input
        code_panels = driver.find_elements(By.XPATH, "//div[contains(@class,'page__login-newUI-code') or contains(@class,'page__login-code-number')]")
        for cp in code_panels:
            text_nodes = cp.find_elements(By.XPATH, ".//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'verification code is sent') or contains(translate(text(), 'abcdefghijklmnopqrstuvwxyz', 'abcdefghijklmnopqrstuvwxyz'), 'verification code is sent')]")
            # also check for 6-digit input visible
            inputs = cp.find_elements(By.XPATH, ".//input[@maxlength='6' or @type='password' or @type='text']")
            visible_inputs = [i for i in inputs if i.is_displayed()]
            if text_nodes or visible_inputs:
                # to avoid false positives, ensure there is a strong sign: either the text with +country or a visible 6-digit input
                has_code_text = any((n.text or '').strip() for n in text_nodes)
                has_visible_code_input = any(True for i in visible_inputs)
                if has_code_text or has_visible_code_input:
                    num_fetcher.update_login_cmnt(conn, phone, 'Successfully Sent')
                    return 'success'
    except Exception:
        pass

    # 3) check for a modal/dialog with the exact 'Verification code send error' title
    try:
        dialogs = driver.find_elements(By.XPATH, "//div[contains(@class,'sui-dialog__body') or contains(@class,'sui-dialog__wrapper')]")
        for d in dialogs:
            try:
                # title/p nodes inside dialog
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

    # nothing matched strictly
    return 'unknown'


def click_close_dialog_button(driver):
    """
    Try to close a sui dialog using the close button.
    The HTML you're using:
    <span ... class="sui-dialog__closebtn" aria-label="close" ...>...</span>
    """
    try:
        wait = WebDriverWait(driver, 4)
        # try to find the close button by aria-label/class
        close_el = None
        try:
            close_el = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(@class,'sui-dialog__closebtn') and (@aria-label='close' or @role='button')]"))
            )
        except TimeoutException:
            # fallback search without waiting for clickable
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
                # try JS click
                try:
                    driver.execute_script("var el = document.querySelector('span.sui-dialog__closebtn[aria-label=\"close\"]'); if(el){ el.click(); }")
                    human_sleep(0.25, 0.6)
                    print("[+] Dialog close clicked by JS")
                    return True
                except Exception:
                    print("[WARN] Couldn't click dialog close button (JS failed)")
                    return False
        else:
            # As a last resort, try to remove any overlay/dialog wrapper via JS to continue
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


# ----------------- MAIN -----------------

def main():
    print("=== SHEIN PHONE FLOW (PHONE FIRST → COUNTRY SECOND) — human-like + accurate ===")

    spot = input("Enter spot number: ").strip() or '1'

    # parse profile range
    def parse_profile_range(raw):
        m = re.match(r"(\d+)\s*,\s*(\d+)", raw or '')
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 0 or b <= 0 or a > b:
            return None
        return a, b

    while True:
        rng_raw = input("Enter profile range (e.g. 1,5): ").strip()
        rng = parse_profile_range(rng_raw)
        if rng:
            break
        print("Invalid range — try again")

    profile_start, profile_end = rng
    range_id = input("Enter range_id: ").strip()

    user_id = num_fetcher.read_user_id_from_file(num_fetcher.USER_FILE)
    conn = num_fetcher.get_db_connection()

    base_dir = rf"C:\smsng_spot{spot}"
    os.makedirs(base_dir, exist_ok=True)

    try:
        for profile in range(profile_start, profile_end + 1):
            print(f"\n--- PROFILE {profile} ---")

            profile_dir = os.path.join(base_dir, f"profile{profile}")
            os.makedirs(profile_dir, exist_ok=True)

            opts = uc.ChromeOptions()
            opts.add_argument(f"--user-data-dir={profile_dir}")
            opts.add_argument("--start-maximized")
            opts.add_argument("--disable-blink-features=AutomationControlled")

            driver = None
            try:
                driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, headless=True)
                driver.get(SHEIN_LOGIN_URL)
                human_sleep(0.8, 1.6)

                # Keep trying numbers until we get case 'success', then move to next profile
                while True:
                    number_row = None
                    phone = None
                    reserved = False

                    # reserve a number with retries
                    for _ in range(RESERVE_TRIES):
                        number_row = num_fetcher.get_random_number(conn, range_id, user_id)
                        if not number_row:
                            break
                        phone = str(number_row["number"])
                        if num_fetcher.reserve_number(conn, phone):
                            reserved = True
                            break

                    if not reserved:
                        print("[ERROR] No number available or reserve failed — moving to next profile")
                        break

                    # attempt loop: try to send the number and detect a clear outcome
                    unknown_tries = 0
                    while True:
                        try:
                            # focus the page and ensure input is empty
                            clear_phone_input_field(driver)
                            human_sleep(0.2, 0.6)

                            # enter phone human-like
                            ok = enter_phone_only(driver, phone)
                            if not ok:
                                raise Exception('Phone input not found or not interactable')

                            human_sleep(0.25, 0.6)

                            # select country based on number_row info
                            if not select_country_after_phone(driver, number_row):
                                # try a fallback: click first country and continue
                                print('[WARN] Country selection fallback — proceeding')

                            human_sleep(0.3, 0.7)

                            # click Continue/Register
                            if not click_continue_sms(driver):
                                raise Exception('Continue/Register button not found')

                            # check for outcome with conservative detection
                            result = detect_case_strict(conn, driver, phone)

                            if result == 'success':
                                print('[+] Verification code sent — success for this profile')
                                # free the number (decrement limit, return to master as before)
                                if reserved and phone:
                                    try:
                                        num_fetcher.free_number(conn, phone)
                                    except Exception:
                                        pass
                                # move to next profile
                                raise StopIteration

                            elif result == 'invalid':
                                print('[*] Number marked invalid — will free and try another number for the same profile')
                                if reserved and phone:
                                    try:
                                        num_fetcher.free_number(conn, phone)
                                    except Exception:
                                        pass
                                human_sleep(0.6, 1.2)
                                break  # break inner while to reserve a new number

                            elif result == 'limit':
                                print('[*] Limit sending error — updated DB and will try next number on same profile')
                                # NEW: attempt to close the dialog so we can continue trying other numbers
                                try:
                                    closed = click_close_dialog_button(driver)
                                    if closed:
                                        human_sleep(0.4, 0.9)
                                    else:
                                        print("[WARN] Could not close the limit dialog - proceeding anyway")
                                except Exception as e:
                                    print(f"[WARN] Exception while trying to close dialog: {e}")

                                if reserved and phone:
                                    try:
                                        num_fetcher.free_number(conn, phone)
                                    except Exception:
                                        pass
                                human_sleep(0.6, 1.2)
                                break

                            else:
                                # unknown result — retry a small number of times before giving up
                                unknown_tries += 1
                                print(f'[?] Unknown result (attempt {unknown_tries}). Retrying after a pause...')
                                if SCREENSHOT_ON_ERROR:
                                    take_screenshot(driver, f"unknown_profile_{profile}_try{unknown_tries}.png")
                                if unknown_tries > MAX_UNKNOWN_RETRIES:
                                    # give up on this number and try another
                                    if reserved and phone:
                                        try:
                                            num_fetcher.free_number(conn, phone)
                                        except Exception:
                                            pass
                                    human_sleep(0.6, 1.2)
                                    break
                                else:
                                    human_sleep(1.0, 2.0)
                                    continue

                        except StopIteration:
                            # success path: break out to next profile
                            break

                        except Exception as e:
                            print(f"[ERROR] Exception during attempt: {e}")
                            if SCREENSHOT_ON_ERROR and driver:
                                take_screenshot(driver, f"attempt_error_profile_{profile}.png")
                            if reserved and phone:
                                try:
                                    num_fetcher.free_number(conn, phone)
                                except Exception:
                                    pass
                            # pause and try next number
                            human_sleep(0.8, 1.6)
                            break

                    # end inner while (per-number attempt loop)

                    # loop will continue to next number (same profile) unless StopIteration occurred
                    # Detect StopIteration via break out to outer try-except: we check page state by searching for success marker
                    # check if we should move to next profile by looking for a success marker element
                    try:
                        # quick check: inside code-area a countdown or code input often appears — use our detection again
                        final_check = detect_case_strict(conn, driver, phone)
                        if final_check == 'success':
                            # go to next profile
                            break
                    except Exception:
                        pass

                    # continue to try another number for same profile
                    continue

            except Exception as e:
                print(f"[FATAL] Browser/profile error: {e}")
                if driver:
                    take_screenshot(driver, f"fatal_profile_{profile}.png")
            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass

        # end profiles loop

    finally:
        try:
            conn.close()
        except Exception:
            pass

    print('\nDONE.')


if __name__ == '__main__':
    main()
