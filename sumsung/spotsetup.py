#!/usr/bin/env python3
"""
create_okx_profiles.py
Create real Chrome user-data dirs directly under C:\
Run Chrome like:
  "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\smsng_spot1\profile1"
"""
import os, sys, json

BASE_DIR = "C:\\"  # spots will be created directly under C:\ (e.g. C:\smsng_spot1)
MAX = 500

def ensure(path):
    try:
        os.makedirs(path, exist_ok=True)
    except PermissionError:
        print("Permission denied. Run as administrator or pick a different BASE_DIR.")
        sys.exit(1)

def make_profile(base, profile_index):
    p = os.path.join(base, f"profile{profile_index}")
    default = os.path.join(p, "Default")
    ensure(default)
    pref = os.path.join(default, "Preferences")
    if not os.path.exists(pref):
        with open(pref, "w", encoding="utf-8") as f:
            json.dump({"profile": {"name": f"profile{profile_index}"}}, f, indent=2)
    print("Ready:", p)

def make_spot(base, spot_index, profiles_per_spot):
    spot_dir = os.path.join(base, f"smsng_spot{spot_index}")
    ensure(spot_dir)
    for j in range(1, profiles_per_spot + 1):
        make_profile(spot_dir, j)

def ask_two_counts():
    raw1 = input("How many working spot you want? ").strip()
    if not raw1.isdigit():
        print("Enter a positive whole number.")
        return ask_two_counts()
    spots = int(raw1)
    raw2 = input("How many profiles you need in each working spot? ").strip()
    if not raw2.isdigit():
        print("Enter a positive whole number.")
        return ask_two_counts()
    profiles = int(raw2)
    if spots <= 0 or spots > MAX or profiles <= 0 or profiles > MAX:
        print(f"Choose values in range 1..{MAX}.")
        return ask_two_counts()
    return spots, profiles

def main():
    if os.name != "nt":
        print("Note: script assumes Windows paths (C:). It will still create directories but test on Windows.")
    ensure(BASE_DIR)
    spots, profiles = ask_two_counts()
    for i in range(1, spots + 1):
        make_spot(BASE_DIR, i, profiles)
    print("\nDone. Launch Chrome with:")
    print(r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\smsng_spot1\profile1"')

if __name__ == "__main__":
    main()
