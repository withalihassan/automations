#!/usr/bin/env python3
"""
Open Chrome using a specific user-data dir and profile and keep both CMD and
the browser open. Works on Windows: searches common chrome.exe locations,
or asks you for the path if not found.

Behavior:
- Ask for multiple spot ids (comma separated and ranges allowed, e.g. "1,2,5-7")
- Ask for single profile number (e.g. 1)
- For each spot id, launch Chrome using user-data-dir = DEFAULT_BASE<spot_id>
  and profile-directory = profile<profile_num>.
- Each launched window opens TWO tabs:
    1) Profile Details (data: page) — shows spot id, profile id, user-data-dir path, profile-directory
    2) The configured URL
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

# target URL to open in the second tab
URL = "https://v3.account.samsung.com/dashboard/security"
DEFAULT_BASE = r"C:\smsng_spot"  # base folder prefix (final dir will be DEFAULT_BASE<spot_id>)

def ask_positive_int(prompt: str) -> int:
    while True:
        s = input(prompt).strip()
        if s.isdigit() and int(s) >= 0:
            return int(s)
        print(" -> enter a positive whole number (e.g. 0, 1, 2).")

def ask_spot_ids(prompt: str) -> List[int]:
    """
    Accepts comma separated numbers and ranges like "1,2,5-8,10"
    Returns a sorted list of unique spot ids as ints.
    """
    while True:
        s = input(prompt).strip()
        if not s:
            print(" -> please enter at least one spot id.")
            continue
        try:
            ids = parse_spot_id_string(s)
            if not ids:
                print(" -> no valid ids found, try again.")
                continue
            return ids
        except ValueError as e:
            print(" ->", e)

def parse_spot_id_string(s: str) -> List[int]:
    parts = re.split(r"[,\s]+", s.strip())
    ids = set()
    for p in parts:
        if not p:
            continue
        # range like 3-7
        m = re.match(r"^(\d+)-(\d+)$", p)
        if m:
            a = int(m.group(1))
            b = int(m.group(2))
            if a > b:
                raise ValueError(f"Invalid range '{p}' (start > end).")
            for n in range(a, b+1):
                ids.add(n)
            continue
        # single number
        if p.isdigit():
            ids.add(int(p))
            continue
        raise ValueError(f"Invalid token '{p}' (use numbers or ranges like 2-5).")
    return sorted(ids)

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

def make_profile_details_data_url(spot_id: int, profile_num: int, user_data_dir: str, profile_name: str) -> str:
    """
    Create a data: URL that when opened sets the tab title and shows profile details.
    Including a small random token ensures the data: URL differs each time.
    """
    title = f"Spot {spot_id} — Profile {profile_num}"
    token = secrets.token_hex(4)
    html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
      body {{ font-family: system-ui, Arial, sans-serif; padding: 12px; line-height:1.4 }}
      h1 {{ font-size: 18px; margin:0 0 8px 0 }}
      pre {{ background:#f5f5f5; padding:8px; border-radius:6px; overflow:auto }}
      small {{ color: #666 }}
    </style>
  </head>
  <body>
    <h1>{title}</h1>
    <p><strong>Spot ID:</strong> {spot_id} &nbsp;&nbsp; <strong>Profile:</strong> {profile_name}</p>
    <p><strong>User data dir:</strong></p>
    <pre>{user_data_dir}</pre>
    <p><small>token: {token}</small></p>
  </body>
</html>"""
    return "data:text/html;charset=utf-8," + urllib.parse.quote(html)

def launch_for_spot(chrome_path: str, spot_id: int, profile_num: int) -> bool:
    user_data_dir = os.path.abspath(f"{DEFAULT_BASE}{spot_id}")
    profile_name = f"profile{profile_num}"
    os.makedirs(user_data_dir, exist_ok=True)

    # Profile details tab (data:)
    details_tab = make_profile_details_data_url(spot_id, profile_num, user_data_dir, profile_name)
    # Second tab: actual URL
    target_tab = URL

    cmd = [
        chrome_path,
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={profile_name}",
        "--no-first-run",
        "--new-window",
        details_tab,
        target_tab
    ]

    try:
        subprocess.Popen(cmd, shell=False)
        return True
    except Exception as e:
        print(f"  [spot {spot_id}] Failed to launch Chrome: {e}")
        return False

def main():
    print("Enter spot ids (comma separated; ranges allowed, e.g. 1,2,5-8):")
    spot_ids = ask_spot_ids("Spot ids -> ")
    profile_num = ask_positive_int("Enter profile number (numeric, e.g. 1) -> ")

    chrome_path = find_chrome_exe()
    if not chrome_path:
        chrome_path = input("Chrome executable not found. Paste full path to chrome.exe -> ").strip()
        if not os.path.exists(chrome_path):
            print("Invalid path. Exiting.")
            return

    print("\n" + "="*60)
    print("Launching Chrome for the following spot ids and profile:")
    print(f"  spot ids       : {spot_ids}")
    print(f"  profile number : profile{profile_num}")
    print(f"  base user dir  : {DEFAULT_BASE}<spot_id>  (created if missing)")
    print(f"  url            : {URL}")
    print(f"  chrome exe     : {chrome_path}")
    print("="*60 + "\n")

    successes = []
    failures = []
    for sid in spot_ids:
        ok = launch_for_spot(chrome_path, sid, profile_num)
        if ok:
            print(f"  [spot {sid}] Launched profile{profile_num} (profile details tab + target URL)")
            successes.append(sid)
        else:
            failures.append(sid)

    print("\nSummary:")
    print(f"  Launched : {len(successes)} -> {successes}" if successes else "  Launched : 0")
    print(f"  Failed   : {len(failures)} -> {failures}" if failures else "  Failed   : 0")

    input("\nPress ENTER to exit this script (the browser windows will remain open).\n")

if __name__ == "__main__":
    main()
