#!/usr/bin/env python3
"""
smtpdev_print_codes_only.py

Fetch messages from the SMTP.dev account and print ONLY the 6-digit
verification code(s) found in visible HTML text for each message.

Also exposes a convenience function `fetch_codes_for_address(address, password=None, api_base=None, api_key=None, timeout=None)`
that returns a list of unique 6-digit verification codes (strings) found for the address.

Output for each message that contains codes (when run as a script):
FOUND 6-DIGIT CODE(S) IN VISIBLE TEXT (not attributes):
304231
"""
import os
import sys
import re
import json
import html as html_module
import requests
from typing import Any, Dict, List
from html.parser import HTMLParser

API_BASE = os.getenv("SMTP_DEV_BASE", "https://api.smtp.dev")
API_KEY = os.getenv("SMTP_DEV_API_KEY", "smtplabs_wu9je5CiV6ezxoELcmk2MYehAzh918uSqK75w7YvjZsRrWRH")
EMAIL = os.getenv("SMTP_DEV_EMAIL", "okx-406001@one.techsolver.site")
PASSWORD = os.getenv("SMTP_DEV_PASSWORD", "04414ec63f88afe710a3cf785cfb323d")

if not API_KEY or not EMAIL:
    # keep same behaviour as before: but allow callers to pass api_key/address into fetch function
    pass

HEADERS = {"X-API-KEY": API_KEY, "Accept": "application/json", "Content-Type": "application/json"}
TIMEOUT = 15

# --- HTML -> text helper (extract visible text only) ---
class HtmlTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: List[str] = []

    def handle_data(self, data: str):
        if data and data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._parts)


def html_to_visible_text(raw_html: str) -> str:
    parser = HtmlTextExtractor()
    try:
        parser.feed(raw_html)
    except Exception:
        # fallback to a crude strip-if-parsing-fails
        text = re.sub(r'<[^>]+>', ' ', raw_html or "")
        return re.sub(r'\s+', ' ', text).strip()
    return parser.get_text()

# --- HTTP helpers ---
def api_get(path: str, params: Dict[str, Any] = None) -> Any:
    url = f"{API_BASE.rstrip('/')}{path}"
    r = requests.get(url, headers=HEADERS, params=params or {}, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return r.text


def api_post(path: str, json_body: Dict[str, Any]) -> Any:
    url = f"{API_BASE.rstrip('/')}{path}"
    r = requests.post(url, headers=HEADERS, json=json_body, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return r.text


def normalize_list(payload: Any) -> List[Dict]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("member", "members", "items", "data"):
            if k in payload and payload[k] is not None:
                val = payload[k]
                return val if isinstance(val, list) else [val]
        return [payload]
    return []

# --- account / mailbox / messages helpers ---
def find_or_create_account(address: str, password: str) -> Dict:
    data = api_get("/accounts", params={"address": address, "page": 1})
    items = normalize_list(data)
    if items:
        return items[0]
    if password:
        created = api_post("/accounts", {"address": address, "password": password})
        return created if isinstance(created, dict) else (created[0] if isinstance(created, list) and created else {})
    raise RuntimeError("Account not found and not created (no password provided or creation failed).")


def get_inbox_mailbox(account_id: str) -> Dict:
    data = api_get(f"/accounts/{account_id}/mailboxes", params={"page": 1})
    boxes = normalize_list(data)
    for b in boxes:
        p = (b.get("path") or b.get("name") or "").lower() if isinstance(b, dict) else ""
        if p == "inbox" or "inbox" in p:
            return b
    raise RuntimeError("INBOX mailbox not found.")


def list_messages(account_id: str, mailbox_id: str) -> List[Dict]:
    path = f"/accounts/{account_id}/mailboxes/{mailbox_id}/messages"
    page = 1
    out = []
    while True:
        data = api_get(path, params={"page": page})
        msgs = normalize_list(data)
        if not msgs:
            break
        out.extend(msgs)
        if isinstance(data, dict):
            view = data.get("view") or {}
            if not view.get("next"):
                break
        else:
            break
        page += 1
    return out


def get_full_message(account_id: str, mailbox_id: str, message_id: str) -> Dict:
    return api_get(f"/accounts/{account_id}/mailboxes/{mailbox_id}/messages/{message_id}")

# --- helper to normalize html field to str ---
def normalize_html_field(field: Any) -> str:
    if field is None:
        return ""
    if isinstance(field, list):
        return "\n".join(str(x) for x in field)
    if isinstance(field, dict):
        # if dict contains HTML-like keys, prefer 'html' or 'intro' if present
        if "html" in field:
            return str(field.get("html") or "")
        return json.dumps(field)
    return str(field)

# --- main: extract visible text and return codes (no printing) ---
def process_message_for_codes(account_id: str, mailbox_id: str, msg_meta: Dict) -> List[str]:
    """Return list of unique 6-digit codes found in visible text for a single message."""
    msg_id = msg_meta.get("id") or msg_meta.get("msgid")
    if not msg_id:
        return []
    try:
        full = get_full_message(account_id, mailbox_id, msg_id)
    except Exception:
        return []

    # If the API wrapped the message, normalize
    if isinstance(full, dict):
        for k in ("member", "members", "data", "items"):
            if k in full and isinstance(full[k], list) and full[k]:
                full = full[k][0]
                break

    # Prefer raw 'html' field if present
    html_field = ""
    if isinstance(full, dict):
        html_field = full.get("html") or ""
    if not html_field:
        html_field = full.get("intro") or full.get("text") or ""

    # If still empty, try to use downloadUrl
    if not html_field and isinstance(full, dict):
        dl = full.get("downloadUrl")
        if dl:
            try:
                r = requests.get(dl, headers=HEADERS, timeout=TIMEOUT)
                r.raise_for_status()
                html_field = r.text
            except Exception:
                html_field = ""

    html_field_str = normalize_html_field(html_field)

    if not html_field_str:
        # nothing to search
        return []

    visible_text = html_to_visible_text(html_field_str)
    # find all 6-digit sequences in visible text (word-boundary anchored)
    codes = re.findall(r'\b([0-9]{6})\b', visible_text)
    # unique preserve order
    seen = set()
    unique_codes = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique_codes.append(c)

    return unique_codes


def fetch_codes_for_address(address: str, password: str = None, api_base: str = None, api_key: str = None, timeout: int = None) -> List[str]:
    """Fetch 6-digit verification codes for `address` and return a list of unique codes.

    Optional overrides: api_base, api_key, timeout. These temporarily override the module
    globals while this function runs and are restored afterwards.
    """
    # Save globals so we can restore them later
    old_api_base = globals().get('API_BASE')
    old_headers = globals().get('HEADERS').copy() if isinstance(globals().get('HEADERS'), dict) else globals().get('HEADERS')
    old_timeout = globals().get('TIMEOUT')

    if api_base:
        globals()['API_BASE'] = api_base
    if api_key:
        globals()['API_KEY'] = api_key
        globals()['HEADERS'] = {"X-API-KEY": api_key, "Accept": "application/json", "Content-Type": "application/json"}
    if timeout:
        globals()['TIMEOUT'] = timeout

    try:
        try:
            acct = find_or_create_account(address, password)
        except Exception:
            return []

        account_id = acct.get('id')
        if not account_id:
            return []

        try:
            inbox = get_inbox_mailbox(account_id)
        except Exception:
            return []

        mailbox_id = inbox.get('id')
        if not mailbox_id:
            return []

        messages = list_messages(account_id, mailbox_id)
        if not messages:
            return []

        out: List[str] = []
        for m in messages:
            codes = process_message_for_codes(account_id, mailbox_id, m)
            for c in codes:
                if c not in out:
                    out.append(c)
        return out
    finally:
        # restore globals
        globals()['API_BASE'] = old_api_base
        globals()['HEADERS'] = old_headers
        globals()['TIMEOUT'] = old_timeout


# When run as a script, keep prior behaviour: print the two-line block for each message that contains codes.
def main():
    try:
        acct = find_or_create_account(EMAIL, PASSWORD)
    except Exception:
        # silent fail per requirement (no extra output)
        return

    account_id = acct.get("id")
    if not account_id:
        return

    try:
        inbox = get_inbox_mailbox(account_id)
    except Exception:
        return

    mailbox_id = inbox.get("id")
    if not mailbox_id:
        return

    messages = list_messages(account_id, mailbox_id)
    if not messages:
        return

    for m in messages:
        codes = process_message_for_codes(account_id, mailbox_id, m)
        if codes:
            print("FOUND 6-DIGIT CODE(S) IN VISIBLE TEXT (not attributes):")
            for c in codes:
                print(c)


if __name__ == "__main__":
    main()
