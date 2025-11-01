#!/usr/bin/env python3
"""
Launch Chrome with a specific user-data dir and profile (minimal + commented).
"""

import os
import ssl
import time
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options

# --- OPTIONAL: skip certificate checks (only if you really need to) ---
ssl._create_default_https_context = ssl._create_unverified_context

CHROME_MAJOR_VERSION = 138  # change if you need a different Chrome major version

def ask_positive_int(prompt: str) -> int:
    """Ask repeatedly until user enters a positive integer."""
    while True:
        s = input(prompt).strip()
        if s.isdigit() and int(s) > 0:
            return int(s)
        print("  -> please enter a positive whole number (e.g. 1, 2, 3).")

def main():
    spot_id = ask_positive_int("Enter spot id (numeric) -> ")
    profile_num = ask_positive_int("Enter profile number (numeric) -> ")

    user_data_dir = rf"C:\smsng_spot{spot_id}"
    profile_name = f"profile{profile_num}"

    # ensure the user-data-dir exists so Chrome can create profile subfolders
    os.makedirs(user_data_dir, exist_ok=True)

    # Nice console output
    print("\n" + "="*48)
    print("  Chrome launcher — using the following settings")
    print("-"*48)
    print(f"  User data dir : {user_data_dir}")
    print(f"  Profile name  : {profile_name}")
    print(f"  Chrome version: {CHROME_MAJOR_VERSION}")
    print("="*48 + "\n")

    options = Options()
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument(f"--profile-directory={profile_name}")

    try:
        driver = uc.Chrome(options=options, version_main=CHROME_MAJOR_VERSION)
    except Exception as e:
        print("Failed to start Chrome:", e)
        return

    try:
        driver.get("https://www.okx.com")
        print("Browser opened. Press ENTER in this console to close everything and exit.")
        input()  # keep browser open until user presses ENTER
    finally:
        driver.quit()
        print("Browser closed. Exiting.")

if __name__ == "__main__":
    main()
