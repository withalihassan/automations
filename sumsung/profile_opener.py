#!/usr/bin/env python3
"""
Open Chrome using a specific user-data dir and profile and keep both CMD and
the browser open. Works on Windows: searches common chrome.exe locations,
or asks you for the path if not found.
"""

import os
import ssl
import subprocess
import shutil

# optional: skip cert checks only if you really need to
ssl._create_default_https_context = ssl._create_unverified_context

URL = "https://v3.account.samsung.com/dashboard/security"
DEFAULT_BASE = r"C:\smsng_spot"  # base folder prefix

def ask_positive_int(prompt: str) -> int:
    while True:
        s = input(prompt).strip()
        if s.isdigit() and int(s) >= 0:
            return int(s)
        print(" -> enter a positive whole number (e.g. 0, 1, 2).")

def find_chrome_exe() -> str | None:
    # common Windows install locations
    prog = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    prog_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
    candidates = [
        os.path.join(prog, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(prog_x86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # try PATH
    which = shutil.which("chrome") or shutil.which("chrome.exe")
    if which:
        return which
    return None

def main():
    spot_id = ask_positive_int("Enter spot id (numeric) -> ")
    profile_num = ask_positive_int("Enter profile number (numeric) -> ")

    user_data_dir = os.path.abspath(f"{DEFAULT_BASE}{spot_id}")
    profile_name = f"profile{profile_num}"  # you wanted 'profile1', 'profile2', etc.
    os.makedirs(user_data_dir, exist_ok=True)

    chrome_path = find_chrome_exe()
    if not chrome_path:
        chrome_path = input("Chrome executable not found. Paste full path to chrome.exe -> ").strip()
        if not os.path.exists(chrome_path):
            print("Invalid path. Exiting.")
            return

    cmd = [
        chrome_path,
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={profile_name}",
        URL
    ]

    print("\n" + "="*60)
    print("Launching Chrome with these settings:")
    print(f"  chrome exe     : {chrome_path}")
    print(f"  user data dir  : {user_data_dir}")
    print(f"  profile name   : {profile_name}")
    print(f"  url            : {URL}")
    print("="*60 + "\n")

    try:
        # Start Chrome as an independent process. It will remain running when this script exits.
        subprocess.Popen(cmd, shell=False)
    except Exception as e:
        print("Failed to launch Chrome:", e)
        return

    print("Chrome launched. The browser process is independent of this script.")
    input("Press ENTER to exit this script (the browser will remain open until you close it).\n")

if __name__ == "__main__":
    main()
