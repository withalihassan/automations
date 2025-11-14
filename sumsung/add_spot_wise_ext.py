#!/usr/bin/env python3
"""
Open Chrome using a specific user-data dir and profile and keep both CMD and
the browser open. Works on Windows: searches common chrome.exe locations,
or asks you for the path if not found.

Behavior:
 - Asks for spot id (numeric)
 - Asks for profile range (examples):
     "1-5"  -> profiles 1,2,3,4,5
     "1,5"  -> treated as range 1..5 (see note)
     "1,3,5" -> profiles 1,3,5
     "1,3,5-7" -> profiles 1,3,5,6,7
 - For each profile it ensures the profile's user-data dir exists and launches Chrome.
"""

from __future__ import annotations
import os
import ssl
import subprocess
import shutil
from typing import List, Set

# optional: skip cert checks only if you really need to
ssl._create_default_https_context = ssl._create_unverified_context

URL = "https://chromewebstore.google.com/detail/buster-captcha-solver-for/mpbjkejclgfgadiemmefgebjfooflfhl?hl=en&pli="
DEFAULT_BASE = r"C:\smsng_spot"  # base folder prefix, full folder will be DEFAULT_BASE + spot_id

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

def parse_profile_range(s: str) -> List[int]:
    """
    Parse profile range input and return sorted list of profile numbers.

    Rules/behavior:
      - Whitespace ignored.
      - If input is exactly two numbers separated only by a single comma (e.g. "1,5"),
        this is treated as a range start..end (inclusive) to match your examples.
      - Otherwise, commas split items. Each item may be:
          - a single integer "3"
          - a dash-range "5-8"
      - Example inputs:
          "1-5" -> [1,2,3,4,5]
          "1,5" -> [1,2,3,4,5]  (special-case: two numbers separated by comma -> range)
          "1,3,5" -> [1,3,5]
          "1,3,5-7" -> [1,3,5,6,7]
    """
    s = s.strip()
    if not s:
        raise ValueError("empty input")

    tokens = [t.strip() for t in s.split(',') if t.strip()]
    nums: Set[int] = set()

    # special-case: exactly two numeric tokens separated by a single comma -> treat as range
    if len(tokens) == 2 and all(tok.isdigit() for tok in tokens):
        a, b = map(int, tokens)
        if a <= b:
            nums.update(range(a, b + 1))
        else:
            nums.update(range(b, a + 1))
        return sorted(nums)

    # otherwise process each token as single int or a-b range
    for tok in tokens:
        if '-' in tok:
            parts = [p.strip() for p in tok.split('-', 1)]
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError(f"invalid range token: '{tok}'")
            a, b = int(parts[0]), int(parts[1])
            if a <= b:
                nums.update(range(a, b + 1))
            else:
                nums.update(range(b, a + 1))
        else:
            if not tok.isdigit():
                raise ValueError(f"invalid token: '{tok}'")
            nums.add(int(tok))

    if not nums:
        raise ValueError("no profile numbers parsed")
    return sorted(nums)

def launch_profile(chrome_path: str, base_user_data_dir: str, profile_num: int, profile_name: str) -> None:
    user_data_dir = os.path.join(base_user_data_dir, profile_name)
    os.makedirs(user_data_dir, exist_ok=True)

    cmd = [
        chrome_path,
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={profile_name}",
        "--start-maximized",  
        URL
    ]

    try:
        subprocess.Popen(cmd, shell=False)
        print(f"[OK] Launched profile {profile_name} -> user-data-dir: {user_data_dir}")
    except Exception as e:
        print(f"[ERR] Failed to launch profile {profile_name}: {e}")

def main():
    print("== Chrome multi-profile launcher ==")
    spot_id = ask_positive_int("Enter spot id (numeric) -> ")
    # accept range input until valid
    while True:
        raw = input("Enter profile range (examples: '1-5', '1,5' (treated as 1..5), '1,3,5-7') -> ").strip()
        try:
            profiles = parse_profile_range(raw)
            break
        except ValueError as exc:
            print(f" -> invalid input: {exc}. Try again.")

    BASE_USER_DATA_DIR = os.path.abspath(f"{DEFAULT_BASE}{spot_id}")
    # keep the same behavior as your original script: each profile points to its own folder
    chrome_path = find_chrome_exe()
    if not chrome_path:
        chrome_path = input("Chrome executable not found. Paste full path to chrome.exe -> ").strip()
        if not os.path.exists(chrome_path):
            print("Invalid path. Exiting.")
            return

    print("\n" + "=" * 60)
    print(f"Spot id base dir : {BASE_USER_DATA_DIR}")
    print(f"Chrome executable: {chrome_path}")
    print(f"Profiles to open : {profiles}")
    print(f"URL to open      : {URL}")
    print("=" * 60 + "\n")

    # create base dir (parent) - this ensures the spot folder exists
    os.makedirs(BASE_USER_DATA_DIR, exist_ok=True)

    for n in profiles:
        profile_name = f"profile{n}"
        launch_profile(chrome_path, BASE_USER_DATA_DIR, n, profile_name)

    print("\nAll done. Chrome processes launched (if no errors).")
    input("Press ENTER to exit this script (the browser(s) will remain open).\n")

if __name__ == "__main__":
    main()
