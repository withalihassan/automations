#!/usr/bin/env python3
"""
Minimal numbers manager updated:

 - reads user_id from ./user.txt (first non-empty line) using read_user_id_from_file
 - get_random_number(conn, range_id, user_id=None)
   returns a dict including: id, range_id, data_value, full_text, country_name,
   country_code, num_limit, number, belong_to, added_at
 - reserve_number(conn, number)  -> sets belong_to='locked' (atomic via SELECT ... FOR UPDATE)
 - free_number(conn, number)     -> sets belong_to='master' if currently 'locked'
 - lock_and_decrement(conn, number) remains for backward compatibility (locks and decrements num_limit)

Requires a `config.py` exporting DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT
"""
import os
import sys
from pathlib import Path
import pymysql
from typing import Optional, Dict, Any
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT

USER_FILE = Path(__file__).resolve().parent / "user.txt"

def get_db_connection():
    # autocommit=False so we can safely use SELECT ... FOR UPDATE in transactions
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
        port=DB_PORT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )

def _safe_int(value: Any) -> int:
    """Convert DB value to int safely (handles str, Decimal, None)."""
    try:
        return int(value)
    except Exception:
        return 0

def read_user_id_from_file(path: Path) -> Optional[str]:
    """Return the first non-empty line from the file, stripped, or None if not present."""
    if not path.exists():
        print(f"user file not found: {path}", file=sys.stderr)
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                candidate = line.strip()
                if candidate:
                    return candidate
    except Exception as e:
        print(f"failed to read user file {path}: {e}", file=sys.stderr)
        return None
    return None

def get_random_number(conn, range_id, user_id: Optional[str]=None) -> Optional[Dict]:
    """
    Pick a random number row that is available (belong_to='master' and num_limit>0)
    for the given range_id. If user_id is provided, filter by user_id as well.
    This does NOT reserve/lock the row — reservation happens via reserve_number().
    Returns a dict with the important columns (including country fields).
    """
    with conn.cursor() as cur:
        base_sql = (
            "SELECT id, user_id, range_id, data_value, full_text, country_name, country_code, "
            "num_limit, number, belong_to, added_at "
            "FROM numbers "
            "WHERE belong_to='master' AND num_limit>0 AND range_id=%s "
        )
        params = [range_id]
        if user_id:
            base_sql += " AND user_id=%s "
            params.append(user_id)
        base_sql += " ORDER BY RAND() LIMIT 1"

        cur.execute(base_sql, tuple(params))
        row = cur.fetchone()
        if not row:
            return None

        # normalize numeric types coming from DB
        row["num_limit"] = _safe_int(row.get("num_limit"))
        return row

def reserve_number(conn, number) -> bool:
    """
    Atomically reserve (lock) the specific number for this process:
      - SELECT ... FOR UPDATE to lock the row
      - ensure belong_to='master'
      - set belong_to='locked'

    Returns True if the reservation succeeded, False otherwise.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, belong_to FROM numbers WHERE number=%s FOR UPDATE", (number,))
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return False
            if row.get("belong_to") != "master":
                conn.rollback()
                return False

            cur.execute(
                "UPDATE numbers SET belong_to='locked' WHERE id=%s AND belong_to='master'",
                (row["id"],)
            )
            if cur.rowcount == 0:
                conn.rollback()
                return False

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise

def lock_and_decrement(conn, number) -> bool:
    """
    Atomically:
      - lock the row (SELECT ... FOR UPDATE)
      - ensure belong_to='master' and num_limit>0
      - set belong_to='locked' and decrement num_limit by 1

    Returns True if the update happened, False otherwise.
    """
    try:
        with conn.cursor() as cur:
            # lock the specific row
            cur.execute("SELECT id, num_limit, belong_to FROM numbers WHERE number=%s FOR UPDATE", (number,))
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return False

            num_limit = _safe_int(row.get("num_limit"))
            if row.get("belong_to") != "master" or num_limit <= 0:
                conn.rollback()
                return False

            # Use the locked row's id and a WHERE guard to make the update safer
            cur.execute(
                "UPDATE numbers "
                "SET belong_to='locked', num_limit = num_limit - 1 "
                "WHERE id=%s AND belong_to='master' AND num_limit>0",
                (row["id"],)
            )
            if cur.rowcount == 0:
                # someone else changed it between SELECT and UPDATE
                conn.rollback()
                return False

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise

def free_number(conn, number) -> bool:
    """
    Mark a previously locked number back to master (free it).
    Does not change num_limit.
    Returns True if the row was updated (previously locked), False otherwise.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE numbers SET belong_to='master' , num_limit = num_limit - 1  WHERE number=%s AND belong_to='locked'", (number,))
            updated = cur.rowcount
        conn.commit()
        return updated > 0
    except Exception:
        conn.rollback()
        raise

def main():
    user_id = read_user_id_from_file(USER_FILE)
    if not user_id:
        print("No user_id available (check user.txt). Exiting.", file=sys.stderr)
        return 1

    conn = get_db_connection()
    try:
        # for demo purpose: prompt range_id so this script can be run manually
        range_id = input("Enter range_id to pick from: ").strip()
        if not range_id:
            print("No range_id provided. Exiting.", file=sys.stderr)
            return 2

        row = get_random_number(conn, range_id, user_id)
        if not row:
            print("No available numbers for range_id =", range_id, "user_id =", user_id)
            return 3

        number = row["number"]
        print("Selected number (not yet reserved):", number)
        print("Country data:", row.get("data_value"), row.get("full_text"), row.get("country_code"))

        # try to reserve
        ok = reserve_number(conn, number)
        if not ok:
            print("Failed to reserve (likely raced with another process). Try again.")
            return 4

        print("Reserved number:", number)

        # --- simulate "display/use" step here ---
        # After you display/use the number, free it back:
        freed = free_number(conn, number)
        if freed:
            print("Number freed back to 'master':", number)
        else:
            print("Failed to free number (it may have been changed).")

        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    exit(main())
