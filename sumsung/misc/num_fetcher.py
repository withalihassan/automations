#!/usr/bin/env python3
"""
Minimal numbers manager:
- reads range_id from ./range.txt (first non-empty line)
- get_random_number(conn, range_id)
- lock_and_decrement(conn, number)
- free_number(conn, number)

Requires a `config.py` exporting DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT
"""

import os
import sys
from pathlib import Path
import pymysql
from typing import Optional, Dict, Any
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT

RANGE_FILE = Path(__file__).resolve().parent / "range.txt"

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

def read_range_id_from_file(path: Path) -> Optional[str]:
    """Return the first non-empty line from the file, stripped, or None if not present."""
    if not path.exists():
        print(f"range file not found: {path}", file=sys.stderr)
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                candidate = line.strip()
                if candidate:
                    return candidate
    except Exception as e:
        print(f"failed to read range file {path}: {e}", file=sys.stderr)
        return None
    return None

def get_random_number(conn, range_id) -> Optional[Dict]:
    """
    Pick a random number row that is available (belong_to='master' and num_limit>0)
    for the given range_id. This does NOT reserve/lock the row — reservation happens
    only when lock_and_decrement() is called.
    """
    with conn.cursor() as cur:
        sql = (
            "SELECT id, range_id, country_name, country_code, num_limit, number, belong_to, added_at "
            "FROM numbers "
            "WHERE belong_to='master' AND num_limit>0 AND range_id=%s "
            "ORDER BY RAND() LIMIT 1"
        )
        cur.execute(sql, (range_id,))
        row = cur.fetchone()
        if not row:
            return None

        # normalize numeric types coming from DB
        row["num_limit"] = _safe_int(row.get("num_limit"))
        return row

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
    """
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE numbers SET belong_to='master' WHERE number=%s AND belong_to='locked'", (number,))
            updated = cur.rowcount
        conn.commit()
        return updated > 0
    except Exception:
        conn.rollback()
        raise

def main():
    range_id = read_range_id_from_file(RANGE_FILE)
    if not range_id:
        print("No range_id available (check range.txt). Exiting.", file=sys.stderr)
        return 1

    conn = get_db_connection()
    try:
        row = get_random_number(conn, range_id)
        if not row:
            print("No available numbers for range_id =", range_id)
            return 2

        number = row["number"]
        print("Selected number (not yet reserved):", number)

        # try to lock and decrement
        ok = lock_and_decrement(conn, number)
        if not ok:
            print("Failed to lock & decrement (likely raced with another process). Try again.")
            return 3

        print("Locked and decremented num_limit for number:", number)

        # --- simulate "display" step here ---
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
