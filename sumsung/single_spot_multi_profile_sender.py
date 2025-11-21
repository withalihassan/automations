#!/usr/bin/env python3
"""
Windows-ready flow for phone verification (Samsung dashboard).

Behavior changes from previous version:
 - Reserves (locks) a number immediately when selected using num_fetcher.reserve_number().
 - After the attempt (success or any error) the number is freed back to master using num_fetcher.free_number().
 - On successful send the script prints "Message sent successfully".
 - If reserving a chosen number races with another process, the script will retry picking/reserving a number a few times.
"""
import os
import sys
import time
import ssl
import certifi
import re
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
RESERVE_TRIES        = 4   # how many times to pick/reserve a number if races happen
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
    """Detect password popup and enter fixed password. If NONE is present,
    treat as a failure (per requested behavior).
    Returns True on success (popup handled), False on any failure or when popup not found.
    """
    wait = WebDriverWait(driver, wait_seconds)

    password_selectors = [
        (By.XPATH, "//input[@type='password' and contains(@class,'MuiInputBase-input') ]"),
        (By.XPATH, "//input[@type='password' and contains(@aria-describedby, '-helper-text') ]"),
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
        # Per requested change: if no password popup is detected, mark profile as failed
        print("[ERROR] No password popup detected — treating as profile failure (per configuration).")
        return False

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
        (By.XPATH, "//img[contains(@src,'close') or contains(@alt,'close') ]"),
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


def select_country_from_row(driver, number_row, wait_seconds=DEFAULT_WAIT_SECONDS):
    """
    Generic country selection using DB-provided values in number_row.
    number_row should contain keys: data_value, full_text, country_code, country_name
    Returns True on success, False otherwise.
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

    try:
        WebDriverWait(driver, 6).until(lambda d: (
            (d.find_element(By.ID, "county-calling-code-select").get_attribute("aria-expanded") == "true")
            or len(d.find_elements(By.XPATH, "//ul[@role='listbox'] | //div[@role='listbox']")) > 0
        ))
    except Exception:
        pass

    time.sleep(0.25)

    # values we will attempt to use (normalize to safe forms)
    data_value = (number_row.get("data_value") or "").strip()
    full_text = (number_row.get("full_text") or "").strip()
    country_name = (number_row.get("country_name") or "").strip()
    country_code = (number_row.get("country_code") or "").strip()  # may include '+'

    strategies = []

    if data_value:
        strategies.append(("data-value", f"//li[@data-value='{data_value}']"))
    if full_text:
        # full_text often contains "United Kingdom (+44)" — match contained text
        strategies.append(("by-fulltext", f"//li[contains(normalize-space(.), '{full_text}')]"))
    if country_name:
        strategies.append(("by-name", f"//li[contains(normalize-space(.), '{country_name}')]"))
    if country_code:
        # match +44 or 44 (strip plus)
        cc_plain = country_code.replace("+", "").strip()
        strategies.append(("by-plus", f"//li[contains(normalize-space(.), '+{cc_plain}') or contains(normalize-space(.), '{cc_plain}')]"))

    # fallback: try common patterns for UK if DB had nothing useful
    if not strategies:
        strategies = [
            ("data-value-GB", "//li[@data-value='GB']"),
            ("by-text-UK", "//li[contains(normalize-space(.), 'United Kingdom') or contains(normalize-space(.), '+44') ]"),
        ]

    for name, xpath in strategies:
        try:
            candidates = driver.find_elements(By.XPATH, xpath)
            if not candidates:
                continue
            for cand in candidates:
                try:
                    text = cand.text.strip()
                    dv = cand.get_attribute("data-value")
                except Exception:
                    text = ""
                    dv = None
                # prefer exact data_value match if we have it
                if data_value and dv and dv.strip().upper() == data_value.strip().upper():
                    print(f"[+] Clicking option by data-value match ({data_value}) -> text: {text[:80]}")
                    if safe_click(driver, cand):
                        time.sleep(0.4)
                        return True
                # otherwise match by text containing full_text or country_name or country_code
                if full_text and full_text in text:
                    print(f"[+] Clicking option by full_text match -> text: {text[:80]}")
                    if safe_click(driver, cand):
                        time.sleep(0.4)
                        return True
                if country_name and country_name in text:
                    print(f"[+] Clicking option by country_name match -> text: {text[:80]}")
                    if safe_click(driver, cand):
                        time.sleep(0.4)
                        return True
                if country_code and country_code in text:
                    print(f"[+] Clicking option by country_code match -> text: {text[:80]}")
                    if safe_click(driver, cand):
                        time.sleep(0.4)
                        return True
            # if none matched preferrably, click first candidate as last resort for this strategy
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

    print("[ERROR] Could not select country from country list using DB-provided values.")
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

    # Try a few different selectors for the Send code button
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
    """
    Wait for the onscreen confirmation message indicating a code was sent.
    Returns the text if found, otherwise None.
    """
    wait = WebDriverWait(driver, wait_seconds)
    try:
        elem = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//*[contains(normalize-space(.), 'verification code has been sent') or contains(normalize-space(.), 'verification code sent') or contains(normalize-space(.), 'code has been sent')]")
        ))
        text = elem.text.strip()
        # print(f"[+] Confirmation message found (raw): {text}")
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


def parse_profile_range_input(raw):
    """Validate and parse input like '1,5' -> (1,5). Ask again if invalid."""
    raw = raw.strip()
    m = re.match(r"^\s*(\d+)\s*,\s*(\d+)\s*$", raw)
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2))
    if a <= 0 or b <= 0 or a > b:
        return None
    return (a, b)


def main():
    print("=== Samsung phone verification flow (Windows) - multi profile range (headless) ===")
    spot = ask("Enter spot number (e.g. 1): ")

    # Get profile range from user, must be two integers separated by a comma
    while True:
        rng_raw = ask("Enter multi profile range (e.g. 1,5): ")
        rng = parse_profile_range_input(rng_raw)
        if not rng:
            print("Invalid range. Please enter two positive integers separated by a comma, e.g. 1,5 (start <= end).")
            continue
        profile_start, profile_end = rng
        break

    # Ask user to input range_id (this is the numeric range_id in your DB)
    range_id = ask("Enter range_id (numeric, as stored in DB): ")

    # Read user_id from misc/user.txt (first non-empty line)
    user_id = num_fetcher.read_user_id_from_file(num_fetcher.USER_FILE)
    if not user_id:
        print(f"[ERROR] No user_id available (check {num_fetcher.USER_FILE}). Exiting.")
        return

    conn = num_fetcher.get_db_connection()

    BASE_USER_DATA_DIR = rf"C:\smsng_spot{spot}"  # per-profile user-data-dir will be created below

    print("\nUsing:")
    print(f"  BASE_USER_DATA_DIR = {BASE_USER_DATA_DIR}")
    print(f"  PROFILE_RANGE      = {profile_start}..{profile_end}")
    print(f"  DB user_id         = {user_id}")
    print(f"  DB range_id        = {range_id}")
    print(f"  FIXED_PASSWORD     = {FIXED_PASSWORD}\n")

    os.makedirs(BASE_USER_DATA_DIR, exist_ok=True)

    # results map: profile_num -> {status: 'ok'|'error', phone: str|None, msg: str}
    results = {}
    total_sent = 0

    for profile_num in range(profile_start, profile_end + 1):
        PROFILE_FOLDER = f"profile{profile_num}"
        profile_path = os.path.join(BASE_USER_DATA_DIR, PROFILE_FOLDER)
        print(f"\n--- Processing profile {profile_num} (folder: {PROFILE_FOLDER}) ---")

        # Ensure profile-specific user-data-dir exists
        try:
            os.makedirs(profile_path, exist_ok=True)
        except Exception as e:
            msg = f"Failed to create profile user-data-dir '{profile_path}': {e}"
            print(f"[ERROR] {msg}")
            results[profile_num] = {"status": "error", "phone": None, "message": msg}
            continue

        number_row = None
        phone = None
        reserved = False

        # Attempt to pick and reserve a number (retry a few times if raced)
        try:
            for attempt in range(1, RESERVE_TRIES + 1):
                number_row = num_fetcher.get_random_number(conn, range_id, user_id)
                if not number_row:
                    msg = f"No available numbers for range_id = {range_id}, user_id = {user_id}."
                    print(f"[ERROR] {msg}")
                    number_row = None
                    break
                phone = str(number_row["number"])
                print(f"[+] Selected number (attempt {attempt}): {phone} (not reserved yet)")

                # Try to reserve it (set belong_to='locked')
                try:
                    ok = num_fetcher.reserve_number(conn, phone)
                    if ok:
                        reserved = True
                        print(f"[+] Reserved number {phone} for this process.")
                        break
                    else:
                        print(f"[*] Reserve failed for {phone} (likely raced). Retrying...")
                        phone = None
                        number_row = None
                        continue
                except Exception as e:
                    print(f"[ERROR] Exception while reserving {phone}: {e}")
                    phone = None
                    number_row = None
                    continue

            if not number_row:
                # no number available/reservable for this profile
                results[profile_num] = {"status": "error", "phone": None, "message": "No reservable number available."}
                continue

            # show a short country summary
            cn = number_row.get("country_name") or number_row.get("full_text") or "Unknown"
            cc = number_row.get("country_code") or ""
            dv = number_row.get("data_value") or ""
            print(f"[+] Country info from DB: data_value={dv} country='{cn}' code='{cc}'")

        except Exception as e:
            msg = f"Failed to fetch/reserve number from DB: {e}"
            print(f"[ERROR] {msg}")
            results[profile_num] = {"status": "error", "phone": None, "message": msg}
            continue

        # Start browser and perform the flow. Ensure we free the reserved number on any exit.
        opts = uc.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-desv-shm-usage")
        profile_user_data_dir = profile_path
        opts.add_argument(f"--user-data-dir={profile_user_data_dir}")
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

        driver = None
        try:
            driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, headless=True)
            driver.get(OKX_PHONE_URL)
            driver.implicitly_wait(2)
            time.sleep(1)

            handled = enter_password_if_popup(driver, wait_seconds=6)
            if not handled:
                msg = "Password popup missing or handling failed — marking profile as failed."
                print(f"[ERROR] {msg}")
                if SCREENSHOT_ON_ERROR:
                    try:
                        take_screenshot(driver, f"password_popup_error_spot{spot}_profile{profile_num}.png")
                    except Exception:
                        pass
                results[profile_num] = {"status": "error", "phone": phone, "message": msg}
                continue

            time.sleep(0.4)

            print("[*] Attempting country selection (first try)...")
            if select_country_from_row(driver, number_row, wait_seconds=DEFAULT_WAIT_SECONDS):
                print("[+] Country selected on first try.")
            else:
                print("[*] Country selection failed on first try — attempting to close cookie/footer popup and retry.")
                close_cookie_popup_if_present(driver, wait_seconds=3)
                time.sleep(0.5)
                if select_country_from_row(driver, number_row, wait_seconds=DEFAULT_WAIT_SECONDS):
                    print("[+] Country selected after closing cookie popup.")
                else:
                    msg = "Selecting country (from DB values) failed even after closing cookie popup."
                    print(f"[ERROR] {msg}")
                    if SCREENSHOT_ON_ERROR:
                        take_screenshot(driver, f"select_country_error_spot{spot}_profile{profile_num}.png")
                    results[profile_num] = {"status": "error", "phone": phone, "message": msg}
                    continue

            time.sleep(0.6)

            if not enter_phone_and_send_code(driver, phone, wait_seconds=DEFAULT_WAIT_SECONDS):
                msg = "Entering phone or clicking Send code failed."
                print(f"[ERROR] {msg}")
                if SCREENSHOT_ON_ERROR:
                    take_screenshot(driver, f"send_code_error_spot{spot}_profile{profile_num}.png")
                results[profile_num] = {"status": "error", "phone": phone, "message": msg}
                continue

            print("[*] Send code clicked — waiting for verification message...")

            msg_text = wait_for_verification_message(driver, wait_seconds=DEFAULT_WAIT_SECONDS)
            if msg_text:
                # Successful flow: report success (but per your request we free the number afterward)
                print("\n=== Result ===")
                print("Message sent successfully")
                print("==============\n")
                results[profile_num] = {"status": "ok", "phone": phone, "message": "Message sent successfully"}
                total_sent += 1
            else:
                if SCREENSHOT_ON_ERROR:
                    take_screenshot(driver, f"verification_message_missing_spot{spot}_profile{profile_num}.png")
                msg = "Verification message not seen; treating as failure for this profile."
                print(f"[ERROR] {msg}")
                results[profile_num] = {"status": "error", "phone": phone, "message": msg}
                continue

            # small delay between profile attempts
            time.sleep(0.7)

        except Exception as e:
            msg = f"Unexpected exception while processing profile {profile_num}: {e}"
            print(f"[ERROR] {msg}")
            if driver and SCREENSHOT_ON_ERROR:
                try:
                    take_screenshot(driver, f"unexpected_error_spot{spot}_profile{profile_num}.png")
                except Exception:
                    pass
            results[profile_num] = {"status": "error", "phone": phone, "message": msg}
        finally:
            # Always attempt to free the number if we reserved it
            if reserved and phone:
                try:
                    freed = num_fetcher.free_number(conn, phone)
                    if freed:
                        print(f"[+] Freed number {phone} back to 'master' with decremented value.")
                    else:
                        print(f"[WARN] Could not free number {phone} (it may no longer be locked).")
                except Exception as e:
                    print(f"[ERROR] Exception while freeing number {phone}: {e}")
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass

    # end for profiles
    try:
        conn.close()
    except Exception:
        pass

    # Summary
    print("\n=== SUMMARY ===")
    print(f"Profiles processed: {profile_start}..{profile_end} (count = {profile_end - profile_start + 1})")
    print(f"Total messages successfully sent: {total_sent}")

    success_profiles = [p for p, r in results.items() if r.get("status") == "ok"]
    failed_profiles = [p for p, r in results.items() if r.get("status") != "ok"]

    if success_profiles:
        print("\nSuccessful profiles:")
        for p in sorted(success_profiles):
            r = results[p]
            print(f"  - profile{p}: phone={r.get('phone')} message='{r.get('message')}'")

    if failed_profiles:
        print("\nProfiles with errors:")
        for p in sorted(failed_profiles):
            r = results.get(p, {})
            print(f"  - profile{p}: phone={r.get('phone')} error='{r.get('message')}'")

    print("\nScript finished.")
    try:
        input("\nPress Enter to exit (window will remain open until you do)...")
    except Exception:
        pass


if __name__ == "__main__":
    main()
