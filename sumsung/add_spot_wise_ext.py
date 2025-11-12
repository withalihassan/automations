#!/usr/bin/env python3
"""
Open Chrome using a specific user-data dir and profile and keep both CMD and
the browser open. Works on Windows: searches common chrome.exe locations,
or asks you for the path if not found.

Behavior changes (this version):
- Ask for a single spot id (e.g. 1)
- Ask for a profile range (e.g. "1,10" or "1-10") and launch profile1..profile10

Everything else is unchanged.
"""

import os
import ssl
import subprocess
import shutil
import re
from typing import List

# optional: skip cert checks only if you really need to
ssl._create_default_https_context = ssl._create_unverified_context

URL = "https://chromewebstore.google.com/detail/buster-captcha-solver-for/mpbjkejclgfgadiemmefgebjfooflfhl?hl=en&pli=1"
# URL = "https://v3.account.samsung.com/dashboard/security"
DEFAULT_BASE = r"C:\smsng_spot"  # base folder prefix


def ask_positive_int(prompt: str) -> int:
    while True:
        s = input(prompt).strip()
        if s.isdigit() and int(s) >= 0:
            return int(s)
        print(" -> enter a positive whole number (e.g. 0, 1, 2).")


def ask_spot_id(prompt: str) -> int:
    """Ask for a single spot id (positive integer)."""
    while True:
        s = input(prompt).strip()
        if not s:
            print(" -> please enter a spot id.")
            continue
        if s.isdigit() and int(s) >= 0:
            return int(s)
        print(" -> enter a positive whole number (e.g. 0, 1, 2).")


def parse_profile_range(s: str) -> List[int]:
    """Parse a profile range given as:
    - single number: "3" -> [3]
    - comma pair: "1,10" -> [1..10]
    - dash range: "1-10" -> [1..10]

    Returns a list of ints (inclusive range). Raises ValueError on bad input.
    """
    if not s:
        raise ValueError("empty profile range")
    s = s.strip()
    # allow either dash or comma as range separator
    m = re.match(r"^(\d+)\s*[-,]\s*(\d+)$", s)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        if a > b:
            raise ValueError(f"Invalid range '{s}' (start > end).")
        return list(range(a, b + 1))
    # single number
    if s.isdigit():
        return [int(s)]
    raise ValueError("Invalid profile range. Use a single number like '3' or a range like '1,10' or '1-10'.")


def ask_profile_range(prompt: str) -> List[int]:
    while True:
        s = input(prompt).strip()
        try:
            profiles = parse_profile_range(s)
            if not profiles:
                print(" -> no valid profile numbers found, try again.")
                continue
            return profiles
        except ValueError as e:
            print(" ->", e)


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


def launch_for_spot(chrome_path: str, spot_id: int, profile_num: int) -> bool:
    user_data_dir = os.path.abspath(f"{DEFAULT_BASE}{spot_id}")
    profile_name = f"profile{profile_num}"
    os.makedirs(user_data_dir, exist_ok=True)

    cmd = [
        chrome_path,
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={profile_name}",
        "--no-first-run",
        "--new-window",
        URL
    ]

    try:
        subprocess.Popen(cmd, shell=False)
        return True
    except Exception as e:
        print(f"  [profile {profile_num}] Failed to launch Chrome for spot {spot_id}: {e}")
        return False


def main():
    print("Enter single spot id (e.g. 1):")
    spot_id = ask_spot_id("Spot id -> ")
    print("Enter profile range (single number '3' or range '1,10' / '1-10'):")
    profile_nums = ask_profile_range("Profile range -> ")

    chrome_path = find_chrome_exe()
    if not chrome_path:
        chrome_path = input("Chrome executable not found. Paste full path to chrome.exe -> ").strip()
        if not os.path.exists(chrome_path):
            print("Invalid path. Exiting.")
            return

    print("\n" + "="*60)
    print("Launching Chrome for the following spot id and profile(s):")
    print(f"  spot id        : {spot_id}")
    print(f"  profiles       : {profile_nums}")
    print(f"  base user dir  : {DEFAULT_BASE}<spot_id>  (created if missing)")
    print(f"  url            : {URL}")
    print(f"  chrome exe     : {chrome_path}")
    print("="*60 + "\n")

    successes: List[int] = []
    failures: List[int] = []
    for pnum in profile_nums:
        ok = launch_for_spot(chrome_path, spot_id, pnum)
        if ok:
            print(f"  [profile {pnum}] Launched for spot {spot_id}")
            successes.append(pnum)
        else:
            failures.append(pnum)

    print("\nSummary:")
    print(f"  Launched : {len(successes)} -> {successes}" if successes else "  Launched : 0")
    print(f"  Failed   : {len(failures)} -> {failures}" if failures else "  Failed   : 0")

    input("\nPress ENTER to exit this script (the browser windows will remain open).\n")


if __name__ == "__main__":
    main()
