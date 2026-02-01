#!/usr/bin/env python3
"""
multi_login.py

- Ask for spot and one or more profile ids (comma-separated) or a range (e.g. "1,5" or "1-5").
  Special case: if the user enters exactly two comma-separated integers (e.g. "1,5") this will be
  interpreted as a inclusive range from 1 to 5 because that's the convention you asked for.

- For each profile id the script will:
  - call misc/email_fetcher.get_email_for_profile(spot, profile)
  - launch a Chrome instance using a dedicated user-data-dir for the spot/profile
  - open a Profile Details tab and the OKX_URL tab
  - click "Sign in" (if present) and enter the fetched email

- After processing all requested profiles the script waits for you to press ENTER and then
  closes all browser windows.

Notes:
- Expects misc/email_fetcher.py with get_email_for_profile(spot, profile) to be importable.
- If an account row isn't found for a given profile the script logs and continues.

"""
from __future__ import annotations
import os
import sys
import time
import ssl
import certifi
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, List
import importlib
import importlib.util
from pprint import pprint

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
OKX_URL              = "https://v3.account.samsung.com/dashboard/intro"
CHROME_MAJOR_VERSION = 144
FIXED_PASSWORD       = "@Smsng#0961"   # reference only
DEFAULT_WAIT_SECONDS = 20
SCREENSHOT_ON_ERROR  = True
# -------------------------------------------------

THIS_DIR = Path(__file__).resolve().parent


def ask(prompt: str, required: bool = True) -> str:
    while True:
        v = input(prompt).strip()
        if required and not v:
            print("Please enter a value.")
            continue
        return v


# ---------- email_fetcher loader ----------
def load_email_fetcher_module() -> object:
    """
    Try to import misc.email_fetcher first; if that fails locate misc/email_fetcher.py
    adjacent to this script and load it with importlib.
    Returns the loaded module object.
    """
    # 1) try import by package name
    try:
        return importlib.import_module("misc.email_fetcher")
    except Exception:
        pass

    # 2) try direct import from misc/email_fetcher.py next to THIS_DIR
    candidate = THIS_DIR / "misc" / "email_fetcher.py"
    if candidate.exists():
        spec = importlib.util.spec_from_file_location("email_fetcher", str(candidate))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            return mod

    # 3) try email_fetcher.py next to THIS_DIR (fallback)
    candidate2 = THIS_DIR / "email_fetcher.py"
    if candidate2.exists():
        spec = importlib.util.spec_from_file_location("email_fetcher", str(candidate2))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            return mod

    raise ImportError(
        "Could not import misc.email_fetcher. Ensure misc/email_fetcher.py exists and is importable."
    )


def get_account_row_for_profile(spot: int, profile: int) -> Optional[Dict[str, Any]]:
    """
    Use the loaded email_fetcher module to fetch the least-recently-used account row.
    Returns the row dict or None.
    """
    mod = load_email_fetcher_module()
    if not hasattr(mod, "get_email_for_profile"):
        raise RuntimeError("Loaded module does not expose get_email_for_profile(spot, profile).")
    return mod.get_email_for_profile(spot, profile)


# ---------- Selenium helpers ----------
def safe_click(driver, element):
    """Scroll element into view and click it, with JS fallback."""
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


def fill_account_email(driver, email: str, wait_seconds: int = DEFAULT_WAIT_SECONDS) -> bool:
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
        time.sleep(0.08)
        input_el.send_keys(email)
        # force blur so React/MUI may pick up value
        input_el.send_keys(Keys.TAB)
        print(f"[+] Entered email: {email}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to enter email: {e}")
        return False


def take_screenshot(driver, name="error_screenshot.png"):
    """Save a screenshot to the current working directory."""
    try:
        path = os.path.join(os.getcwd(), name)
        driver.save_screenshot(path)
        print(f"[+] Screenshot saved to {path}")
    except Exception as e:
        print(f"[ERROR] Failed to save screenshot: {e}")


def build_profile_details_data_url(spot: int, profile_num: int, email: str) -> str:
    """Return a safe data:text/html URL that displays spot, profile, email."""
    html = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <title>Profile Details - Spot {spot} / Profile {profile_num}</title>
        <style>
          body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial; padding: 24px; }}
          h1 {{ font-size: 22px; margin-bottom: 12px; }}
          .item {{ margin-bottom: 8px; font-size: 16px; }}
          b {{ color: #0a66c2; }}
        </style>
      </head>
      <body>
        <h1>Profile Details</h1>
        <div class="item"><b>Spot ID:</b> {spot}</div>
        <div class="item"><b>Profile ID:</b> {profile_num}</div>
        <div class="item"><b>Email:</b> {email}</div>
        <div class="item"><b>Email:</b>@Smsng#860</div>
      </body>
    </html>
    """
    return "data:text/html;charset=utf-8," + urllib.parse.quote(html)


# ---------- helpers for profile parsing ----------
def parse_profiles_input(s: str) -> List[int]:
    """
    Parse a profile input string and return a list of ints.

    Accepts formats like:
      - "1,3,5" -> [1,3,5]
      - "1-5" -> [1,2,3,4,5]
      - "1,5" -> interpreted as range [1..5] (per your request)
    """
    s = s.strip()
    if not s:
        return []

    tokens = [t.strip() for t in s.split(',') if t.strip()]

    # special case: exactly two comma-separated ints -> treat as inclusive range
    if len(tokens) == 2:
        try:
            a = int(tokens[0])
            b = int(tokens[1])
            if a <= b:
                return list(range(a, b + 1))
        except ValueError:
            pass

    result = set()
    for tok in tokens:
        if '-' in tok:
            parts = [p.strip() for p in tok.split('-', 1)]
            if len(parts) == 2:
                try:
                    a = int(parts[0]); b = int(parts[1])
                    if a <= b:
                        for n in range(a, b+1):
                            result.add(n)
                except ValueError:
                    continue
        else:
            try:
                result.add(int(tok))
            except ValueError:
                continue

    return sorted(result)


# ---------- Main multi-login flow ----------

def open_profile_in_browser(spot_in: int, profile_in: int, email: str) -> Optional[uc.Chrome]:
    """Launch a Chrome instance for the given spot/profile and perform the login/email fill.
    Returns the driver instance (so caller can close it later) or None on failure.
    """
    BASE_USER_DATA_DIR = rf"C:\\smsng_spot{spot_in}"
    PROFILE_FOLDER = f"profile{profile_in}"
    user_data_dir = os.path.join(BASE_USER_DATA_DIR, PROFILE_FOLDER)
    os.makedirs(BASE_USER_DATA_DIR, exist_ok=True)

    print(f"\n[+] Launching Chrome for Spot {spot_in} Profile {profile_in} (user-data-dir={user_data_dir})")

    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument(f"--profile-directory={PROFILE_FOLDER}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    chrome_bin = r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    if os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin
        print(f"[+] Using Chrome binary at: {chrome_bin}")

    try:
        driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, headless=False)
    except Exception as e:
        print(f"[ERROR] Failed to launch Chrome for profile {profile_in}: {e}")
        return None

    try:
        try:
            driver.maximize_window()
            time.sleep(0.25)
        except Exception:
            pass

        details_data_url = build_profile_details_data_url(spot_in, profile_in, email)
        existing_handles = set(driver.window_handles)

        # open two new tabs
        driver.execute_script("window.open('about:blank'); window.open('about:blank');")
        time.sleep(0.3)

        all_handles = driver.window_handles
        new_handles = [h for h in all_handles if h not in existing_handles]

        if len(new_handles) >= 2:
            driver.switch_to.window(new_handles[0])
            driver.get(details_data_url)
            time.sleep(0.25)

            driver.switch_to.window(new_handles[1])
            driver.get(OKX_URL)
            driver.implicitly_wait(2)
            time.sleep(0.8)
        else:
            print("[!] Could not detect two new tabs. Using fallback navigation (may affect existing tabs).")
            driver.get(details_data_url)
            time.sleep(0.2)
            driver.execute_script("window.open('about:blank');")
            time.sleep(0.12)
            handles = driver.window_handles
            driver.switch_to.window(handles[-1])
            driver.get(OKX_URL)
            driver.implicitly_wait(2)
            time.sleep(0.8)

        try:
            click_sign_in_button(driver, wait_seconds=8)
        except Exception as e:
            print(f"[*] click_sign_in_button raised: {e} (continuing)")

        time.sleep(0.8)

        if not fill_account_email(driver, email, wait_seconds=DEFAULT_WAIT_SECONDS):
            print(f"[ERROR] Could not fill account input for profile {profile_in}.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, f"fill_account_error_spot{spot_in}_profile{profile_in}.png")
        else:
            print(f"[+] Email entry complete on OKX page for profile {profile_in}.")

        return driver

    except Exception as e:
        print(f"[ERROR] Unexpected exception while processing profile {profile_in}: {e}")
        if SCREENSHOT_ON_ERROR:
            try:
                take_screenshot(driver, f"unexpected_error_spot{spot_in}_profile{profile_in}.png")
            except Exception:
                pass
        try:
            driver.quit()
        except Exception:
            pass
        return None


def main():
    try:
        spot_in = int(ask("Enter spot number (e.g. 1): "))
    except ValueError:
        print("[ERROR] Spot must be an integer.")
        return

    profiles_input = ask("Enter profile(s): comma-separated (e.g. 1,3,5) or range (1-5). Note: '1,5' -> treated as range 1..5: ")
    profiles = parse_profiles_input(profiles_input)
    if not profiles:
        print("[ERROR] No valid profiles parsed from input.")
        return

    print(f"[*] Parsed profiles: {profiles}")

    drivers = []

    for profile_in in profiles:
        print(f"\n[*] Fetching account for Spot {spot_in}, Profile {profile_in}...")
        try:
            row = get_account_row_for_profile(spot_in, profile_in)
        except Exception as e:
            print(f"[ERROR] Failed to load/call email_fetcher for profile {profile_in}: {e}")
            continue

        if not row:
            print(f"[WARN] No account found for spot {spot_in}, profile {profile_in}. Skipping.")
            continue

        email = row.get("email")
        if not email:
            print(f"[WARN] Fetched row doesn't contain an 'email' field for profile {profile_in}. Row:")
            pprint(row)
            continue

        print(f"[+] Found account row. Using email: {email}")

        driver = open_profile_in_browser(spot_in, profile_in, email)
        if driver:
            drivers.append(driver)

    if not drivers:
        print("[!] No browsers were successfully launched. Exiting.")
        return

    print("\nAll requested profiles have been opened.\n")
    input("Press ENTER to close all browsers and quit...\n")

    # cleanup
    for driver in drivers:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
