#!/usr/bin/env python3
"""
Numbers manager updated: safer DB updates and login_cmnt helper.

This keeps the same behavior of reserving/freeing numbers but adds the
`update_login_cmnt` helper which commits the comment immediately.
"""
import os
import sys
from pathlib import Path
import pymysql
from typing import Optional, Dict, Any
from config import DB_HOST, DB_NAME, DB_PASS, DB_PORT, DB_USER

USER_FILE = Path(__file__).resolve().parent / "user.txt"


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
        port=DB_PORT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def read_user_id_from_file(path: Path) -> Optional[str]:
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

        row["num_limit"] = _safe_int(row.get("num_limit"))
        return row


def reserve_number(conn, number) -> bool:
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
                (row["id"],),
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
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, num_limit, belong_to FROM numbers WHERE number=%s FOR UPDATE",
                (number,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return False

            num_limit = _safe_int(row.get("num_limit"))
            if row.get("belong_to") != "master" or num_limit <= 0:
                conn.rollback()
                return False

            cur.execute(
                "UPDATE numbers SET belong_to='locked', num_limit = num_limit - 1 WHERE id=%s AND belong_to='master' AND num_limit>0",
                (row["id"],),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return False

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def free_number(conn, number) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE numbers SET belong_to='master' , num_limit = num_limit - 1  WHERE number=%s AND belong_to='locked'",
                (number,),
            )
            updated = cur.rowcount
        conn.commit()
        return updated > 0
    except Exception:
        conn.rollback()
        raise


def update_login_cmnt(conn, number, comment) -> bool:
    """Update the login_cmnt column for the given number and commit immediately."""
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE numbers SET login_cmnt=%s WHERE number=%s", (comment, number))
            updated = cur.rowcount
        conn.commit()
        return updated > 0
    except Exception:
        conn.rollback()
        raise


# CLI helper (unchanged behavior for manual testing)
if __name__ == '__main__':
    user_id = read_user_id_from_file(USER_FILE)
    if not user_id:
        print('No user_id found in user.txt')
        sys.exit(1)
    conn = get_db_connection()
    try:
        range_id = input('Enter range_id to pick from: ').strip()
        row = get_random_number(conn, range_id, user_id)
        if not row:
            print('No available numbers')
            sys.exit(2)
        number = row['number']
        print('Selected number:', number)
        ok = reserve_number(conn, number)
        print('Reserved' if ok else 'Reserve failed')
    finally:
        conn.close()