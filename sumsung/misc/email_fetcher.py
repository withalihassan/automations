#!/usr/bin/env python3
"""
email_fetcher.py

Fetch the least-recently-used account row for a given spot_id/profile_id.

Usage (module):
    from misc.email_fetcher import get_email_for_profile
    row = get_email_for_profile(spot_id, profile_id)

Usage (CLI):
    python misc/email_fetcher.py --spot 1 --profile 1

Notes:
 - Expects config.py exporting DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT
   (this script will try to import it normally and also try to load it from
   common local locations if normal import fails).
 - Requires pymysql.
"""
from __future__ import annotations
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any
import importlib.util
import pymysql
from pymysql.cursors import DictCursor

THIS_DIR = Path(__file__).resolve().parent

# possible locations to search for config.py (tries in order)
_CONFIG_SEARCH_PATHS = [
    THIS_DIR / "config.py",
    THIS_DIR.parent / "config.py",
    THIS_DIR / "misc" / "config.py",
]

def _load_config_module() -> object:
    """
    Try normal import first; if that fails attempt to load a config.py
    located next to this script (or in parent/misc).
    Returns a module-like object exposing DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT.
    """
    # try normal import
    try:
        import config  # type: ignore
        return config
    except Exception:
        pass

    # attempt to find a config.py in the common search paths
    for p in _CONFIG_SEARCH_PATHS:
        if p.exists():
            spec = importlib.util.spec_from_file_location("config", str(p))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore
                return mod

    # fallback: try adding THIS_DIR to sys.path and import again
    sys.path.insert(0, str(THIS_DIR))
    try:
        import config  # type: ignore
        return config
    except Exception as e:
        raise RuntimeError(
            "Unable to import config.py. Place config.py next to this script "
            "or ensure it's discoverable on PYTHONPATH."
        ) from e

# load config values (raises descriptive error if missing)
_cfg = _load_config_module()
try:
    DB_HOST = _cfg.DB_HOST
    DB_NAME = _cfg.DB_NAME
    DB_USER = _cfg.DB_USER
    DB_PASS = _cfg.DB_PASS
    DB_PORT = int(getattr(_cfg, "DB_PORT", 3306))
except AttributeError as e:
    raise RuntimeError("config.py is missing one of DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT") from e

# Range file: prefer misc/range.txt (per your doc) otherwise range.txt next to this script
if (THIS_DIR / "misc" / "range.txt").exists():
    RANGE_FILE = THIS_DIR / "misc" / "range.txt"
else:
    RANGE_FILE = THIS_DIR / "range.txt"

def read_range_id_from_file(path: Path) -> Optional[str]:
    """Return the first non-empty line from the file, stripped, or None if not present."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                candidate = line.strip()
                if candidate:
                    return candidate
    except Exception:
        return None
    return None

def get_db_connection():
    """Return a pymysql connection (autocommit True for simple selects)."""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
        port=DB_PORT,
        cursorclass=DictCursor,
        autocommit=True
    )

def get_email_for_profile(spot_id: int, profile_id: int) -> Optional[Dict[str, Any]]:
    """
    Return a dict with account fields for the given spot_id and profile_id,
    matching range_id from RANGE_FILE as well (if available).
    Expected fields returned include at least:
      - email
      - email_psw
      - (other fields from your accounts table)
    Returns None if no matching row found.
    """
    range_id = read_range_id_from_file(RANGE_FILE)
    q = (
        "SELECT `id`, `by_user`, `range_id`, `email`, `email_psw`, `email_otp`, `spot_id`, "
        "`profile_id`, `account_psw`, `ac_status`, `ac_last_used`, `created_at` "
        "FROM `accounts` WHERE spot_id=%s AND profile_id=%s"
    )
    params = [spot_id, profile_id]
    if range_id:
        q += " AND range_id=%s"
        params.append(range_id)

    # prefer least recently used (NULLs sort first by default in MySQL), limit 1
    q += " ORDER BY ac_last_used ASC LIMIT 1"

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(q, tuple(params))
            row = cur.fetchone()
            if not row:
                return None
            return row
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

# CLI convenience (keeps your original CLI)
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Fetch account/email for a spot/profile.")
    p.add_argument("--spot", type=int, required=True, help="spot_id (int)")
    p.add_argument("--profile", type=int, required=True, help="profile_id (int)")
    args = p.parse_args()
    r = get_email_for_profile(args.spot, args.profile)
    if not r:
        print("No account found for spot", args.spot, "profile", args.profile)
    else:
        from pprint import pprint
        print("Found:")
        pprint(r)
