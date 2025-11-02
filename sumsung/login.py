#!/usr/bin/env python3
"""
Launch Chrome using a chosen Windows user-data folder and profile.
Prompts the user for:
 - spot number  -> used to build C:\smsng_spot{spot}
 - profile num  -> used to build profile_{profile}
 - email        -> collected (password is fixed)
Password is always: @Smsng#0961
"""
import os
import ssl
import certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
import undetected_chromedriver as uc

OKX_URL = "https://v3.account.samsung.com/dashboard/security"
CHROME_MAJOR_VERSION = 141
FIXED_PASSWORD = "@Smsng#0961"

def ask(prompt, required=True):
    while True:
        v = input(prompt).strip()
        if not v and required:
            print("Please enter a value.")
            continue
        return v

def main():
    spot = ask("Enter spot number (e.g. 1 or 2): ")
    profile = ask("Enter profile number (e.g. 1): ")
    email = ask("Enter email: ")

    BASE_USER_DATA_DIR = rf"C:\smsng_spot{spot}"
    PROFILE_FOLDER = f"profile_{profile}"

    print(f"\nUsing:\n  BASE_USER_DATA_DIR = {BASE_USER_DATA_DIR}\n  PROFILE_FOLDER     = {PROFILE_FOLDER}\n  EMAIL              = {email}\n  PASSWORD           = {FIXED_PASSWORD}\n")

    os.makedirs(BASE_USER_DATA_DIR, exist_ok=True)

    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={BASE_USER_DATA_DIR}")
    opts.add_argument(f"--profile-directory={PROFILE_FOLDER}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")

    # Optional: explicit Chrome binary path on Windows
    chrome_bin = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin

    driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, headless=False)
    try:
        driver.get(OKX_URL)
        driver.implicitly_wait(5)
        input("Press ENTER to close the browser and quit...")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
