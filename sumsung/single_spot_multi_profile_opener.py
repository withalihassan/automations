#!/usr/bin/env python3
"""
Launch Chrome for a single spot id and a range of profile numbers.

Behavior:
- Ask for a single spot id first (numeric, e.g. 1)
- Ask for a profile range next (e.g. "1,5" or "1-5") -> opens profile1 .. profile5
- For each profile number in the range:
    * create user-data-dir = DEFAULT_BASE + <spot_id> (if missing)
    * launch Chrome with profile-directory=profile<profile_num>
    * open two tabs:
        1) a small data: page whose <title> is "Spot <spot_id> — Profile <profile_num> — Random"
        2) the configured URL
- Keeps the script open until user presses ENTER (browser windows remain open).
"""

from __future__ import annotations
import os
import ssl
import subprocess
import shutil
import re
import secrets
import urllib.parse
from typing import List

# optional: skip cert checks only if you really need to
ssl._create_default_https_context = ssl._create_unverified_context

URL = "https://v3.account.samsung.com/dashboard/security"
DEFAULT_BASE = r"C:\smsng_spot"  # base folder prefix; final dir will be DEFAULT_BASE<spot_id>

def ask_positive_int(prompt: str) -> int:
    while True:
        s = input(prompt).strip()
        if s.isdigit() and int(s) >= 0:
            return int(s)
        print(" -> enter a positive whole number (e.g. 0, 1, 2).")

def ask_profile_range(prompt: str) -> List[int]:
    """
    Accepts either a pair 'start,end' or 'start-end' (e.g. "1,5" or "1-5")
    or a single number "3". Returns the inclusive list of profile numbers.
    """
    while True:
        s = input(prompt).strip()
        if not s:
            print(" -> please enter a profile range (e.g. 1,5 or 1-5) or a single number.")
            continue
        s_clean = s.replace(" ", "")
        # match start,end or start-end
        m = re.match(r"^(\d+)[,-](\d+)$", s_clean)
        if m:
            a = int(m.group(1)); b = int(m.group(2))
            if a > b:
                print(" -> invalid range (start > end). Enter like '1,5' for profiles 1..5.")
                continue
            return list(range(a, b + 1))
        # single number
        if s_clean.isdigit():
            return [int(s_clean)]
        print(" -> invalid input. Use 'start,end' or 'start-end' (e.g. 1,5) or a single number.")

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

def make_random_tab_data_url(spot_id: int, profile_num: int) -> str:
    """
    Create a data: URL that when opened sets the tab title to include spot & profile.
    We include a random token so it's slightly different each time.
    """
    title = f"Spot {spot_id} — Profile {profile_num} — Random"
    random_token = secrets.token_hex(4)
    html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>{title}</title>
  </head>
  <body>
    <h1>{title}</h1>
    <p>token: {random_token}</p>
  </body>
</html>"""
    return "data:text/html;charset=utf-8," + urllib.parse.quote(html)

def launch_for_profile(chrome_path: str, spot_id: int, profile_num: int, url: str) -> bool:
    user_data_dir = os.path.abspath(f"{DEFAULT_BASE}{spot_id}")
    profile_name = f"profile{profile_num}"
    os.makedirs(user_data_dir, exist_ok=True)

    # first tab: data: page with title showing spot/profile (randomized token inside)
    data_tab = make_random_tab_data_url(spot_id, profile_num)
    # second tab: the real target URL
    second_tab = url

    cmd = [
        chrome_path,
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={profile_name}",
        "--no-first-run",
        "--new-window",
        data_tab,
        second_tab
    ]

    try:
        subprocess.Popen(cmd, shell=False)
        return True
    except Exception as e:
        print(f"  [profile {profile_num}] Failed to launch Chrome: {e}")
        return False

def main():
    # ask spot id first
    spot_id = ask_positive_int("Enter single spot id (numeric, e.g. 1) -> ")

    print("Enter profile range (e.g. '1,5' or '1-5' to open profiles 1 through 5).")
    profiles = ask_profile_range("Profile range -> ")

    chrome_path = find_chrome_exe()
    if not chrome_path:
        chrome_path = input("Chrome executable not found. Paste full path to chrome.exe -> ").strip()
        if not os.path.exists(chrome_path):
            print("Invalid path. Exiting.")
            return

    print("\n" + "="*60)
    print("Launching Chrome for spot and profile range:")
    print(f"  spot id        : {spot_id}")
    print(f"  profiles       : {profiles}")
    print(f"  profile dir(s) : profileN (under user-data-dir)")
    print(f"  base user dir  : {DEFAULT_BASE}<spot_id>  (created if missing)")
    print(f"  url            : {URL}")
    print(f"  chrome exe     : {chrome_path}")
    print("="*60 + "\n")

    successes = []
    failures = []
    for p in profiles:
        ok = launch_for_profile(chrome_path, spot_id, p, URL)
        if ok:
            print(f"  [profile {p}] Launched (spot {spot_id})")
            successes.append(p)
        else:
            failures.append(p)

    print("\nSummary:")
    if successes:
        print(f"  Launched : {len(successes)} -> {successes}")
    else:
        print("  Launched : 0")
    if failures:
        print(f"  Failed   : {len(failures)} -> {failures}")
    else:
        print("  Failed   : 0")

    input("\nPress ENTER to exit this script (browser windows will remain open).\n")

if __name__ == "__main__":
    main()
