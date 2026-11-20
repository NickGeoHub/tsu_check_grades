#!/usr/bin/env python3
"""
Uni grade watcher (JSON API version, built for uni.tsu.ge).

Logs in via POST /api/Auth/Login (cookie session), fetches the grades endpoint,
flattens the JSON and sends a Telegram message when anything changes.

Usage:
    python check_grades.py              # normal check (run from cron)
    python check_grades.py chat-id      # get chat id
    python check_grades.py inspect      # show login response + grades response structure
    python check_grades.py test-telegram
    python check_grades.py reset        # forget saved state (next run = new baseline)

Setup: pip install requests
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "state.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"


class PortalError(Exception):
    pass


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit("config.json not found. Copy config.example.json to config.json and fill it in.")
    cfg = json.loads(CONFIG_PATH.read_text())
    cfg["username"] = os.environ.get("PORTAL_USER", cfg.get("username", ""))
    cfg["password"] = os.environ.get("PORTAL_PASS", cfg.get("password", ""))
    cfg["telegram_token"] = os.environ.get("TG_TOKEN", cfg.get("telegram_token", ""))
    cfg["telegram_chat_id"] = os.environ.get("TG_CHAT_ID", cfg.get("telegram_chat_id", ""))
    return cfg


def load_state():
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def notify(cfg, text):
    token = cfg["telegram_token"]
    chats = cfg["telegram_chat_id"]
    chats = chats if isinstance(chats, list) else [chats]
    if not token or not any(chats):
        log("Telegram not configured; message would be:\n" + text)
        return False
    ok = False
    for chat in chats:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
            timeout=20,
        )
        if not r.ok:
            log(f"Telegram error {r.status_code} for {chat}: {r.text}")
        ok = ok or r.ok
    return ok


def notify_hhh(cfg, text):
    token, chat = cfg["telegram_token"], cfg["telegram_chat_id"]
    if not token or not chat:
        log("Telegram not configured; message would be:\n" + text)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
        timeout=20,
    )
    if not r.ok:
        log(f"Telegram error {r.status_code}: {r.text}")
    return r.ok


# ---------- Portal ----------

def fill(value, cfg):
    """Replace {user}/{pass} placeholders in the login payload."""
    if isinstance(value, str):
        return value.replace("{user}", cfg["username"]).replace("{pass}", cfg["password"])
    if isinstance(value, dict):
        return {k: fill(v, cfg) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, cfg) for v in value]
    return value


def new_session(cfg):
    base = cfg["base_url"].rstrip("/")
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Origin": base,
        "Referer": base + "/login",
    })
    s.get(base + "/", timeout=30)  # picks up the load-balancer cookie (cookiesession1)
    return s


def login(cfg, s):
    base = cfg["base_url"].rstrip("/")
    r = s.post(base + cfg["login_path"], json=fill(cfg["login_payload"], cfg), timeout=30)
    if r.status_code != 200:
        raise PortalError(f"Login failed: HTTP {r.status_code}: {r.text[:200]}")
    if not any("AspNetCore" in c.name for c in s.cookies):
        raise PortalError("Login returned 200 but no session cookie was set "
                          "(wrong credentials, or the server wants something else). Run: inspect")
    return r


def fetch_grades(cfg, s):
    base = cfg["base_url"].rstrip("/")
    method = cfg.get("grades_method", "GET").upper()
    body = cfg.get("grades_body")
    if body is None and method == "POST":
        body = {}  # ASP.NET answers 415 to a POST without a JSON content-type
    kw = {"json": body} if body is not None else {}
    r = s.request(method, base + cfg["grades_path"], timeout=30, **kw)
    if r.status_code in (401, 403):
        raise PortalError(f"Grades request HTTP {r.status_code} (not logged in?)")
    if r.status_code != 200:
        raise PortalError(f"Grades request HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        if "html" in r.headers.get("Content-Type", "").lower() or "<!doctype html" in r.text[:200].lower():
            raise PortalError(
                f"grades_path '{cfg['grades_path']}' returned the portal's HTML page, not JSON. "
                "It must be the /api/... XHR request behind the grades page "
                "(DevTools -> Network -> Fetch/XHR), not the page's own URL.")
        raise PortalError("Grades endpoint did not return JSON: " + r.text[:200])


def flatten(obj, ignore, prefix=""):
    """JSON -> sorted list of 'path = value' lines."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ignore:
                continue
            out += flatten(v, ignore, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += flatten(v, ignore, f"{prefix}[{i}]")
    else:
        out.append(f"{prefix} = {obj}")
    return out


def get_lines(cfg):
    s = new_session(cfg)
    login(cfg, s)
    data = fetch_grades(cfg, s)
    return flatten(data, set(cfg.get("ignore_keys", []))), data


# ---------- Commands ----------

def cmd_check(cfg):
    state = load_state()
    try:
        lines, _ = get_lines(cfg)
    except (PortalError, requests.RequestException) as e:
        fails = state.get("consecutive_failures", 0) + 1
        state["consecutive_failures"] = fails
        save_state(state)
        log(f"ERROR ({fails} in a row): {e}")
        if fails == 3:
            notify(cfg, f"⚠️ Grade watcher failing 3 times in a row:\n{e}")
        sys.exit(1)

    state["consecutive_failures"] = 0
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()

    if "digest" not in state:
        state.update(digest=digest, lines=lines)
        save_state(state)
        log(f"Baseline saved ({len(lines)} values).")
        notify(cfg, f"✅ Grade watcher is running. Baseline saved ({len(lines)} values).")
        return

    if digest == state["digest"]:
        save_state(state)
        log("No change.")
        return

    old = state["lines"]
    added = [l for l in lines if l not in set(old)]
    removed = [l for l in old if l not in set(lines)]
    msg = "📚 Grades changed!\n"
    if added:
        msg += "\nNew / changed:\n" + "\n".join("+ " + l for l in added[:30])
    if removed:
        msg += "\n\nGone / old value:\n" + "\n".join("- " + l for l in removed[:15])
    if notify(cfg, msg):
        state.update(digest=digest, lines=lines)  # advance baseline only if delivered
        log("Change detected, notified.")
    save_state(state)


def short(v, n=60):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def cmd_inspect(cfg):
    s = new_session(cfg)
    print("Cookies after GET /:", [c.name for c in s.cookies])
    try:
        r = login(cfg, s)
    except (PortalError, requests.RequestException) as e:
        print("!! Login failed:", e)
        print("Check login_payload field names against DevTools -> Network -> Auth/Login -> Payload.")
        return
    print("Login OK. Cookies:", [c.name for c in s.cookies])
    try:
        body = r.json()
        (HERE / "debug_login.json").write_text(json.dumps(body, indent=2, ensure_ascii=False))
        print("\nLogin response structure (saved to debug_login.json, may contain personal data):")
        for l in flatten(body, set())[:40]:
            k, _, v = l.partition(" = ")
            print("  ", k, "=", short(v, 30))
    except ValueError:
        print("Login response is not JSON:", r.text[:200])

    if not cfg.get("grades_path"):
        print("\ngrades_path is empty. Open the grades page in the browser, find the XHR that "
              "returns your grades, and put its path in config.json.")
        return
    try:
        data = fetch_grades(cfg, s)
    except (PortalError, requests.RequestException) as e:
        print("!! Grades request failed:", e)
        return
    (HERE / "debug_grades.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    lines = flatten(data, set(cfg.get("ignore_keys", [])))
    print(f"\nGrades response: {len(lines)} values (saved to debug_grades.json). First 40:\n")
    for l in lines[:40]:
        print("  ", l)
    print("\nIf you see your courses/grades, you're done. Keys that change on every request "
          "(timestamps etc.) go into ignore_keys.")


def cmd_chat_id(cfg):
    token = cfg["telegram_token"]
    if not token:
        sys.exit("Set telegram_token in config.json first.")
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    if not r.ok:
        sys.exit(f"Telegram error {r.status_code}: {r.text}  (token wrong?)")
    chats = {}
    for u in r.json().get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        c = msg.get("chat")
        if c:
            chats[c["id"]] = c.get("username") or c.get("first_name") or c.get("title") or ""
    if not chats:
        sys.exit("No messages found. Open your bot in Telegram, press Start, send it any message, "
                 "then run this again.")
    for cid, name in chats.items():
        print(f"chat_id: {cid}   ({name})")
    print('\nPut the number in config.json as "telegram_chat_id".')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "reset":
        STATE_PATH.unlink(missing_ok=True)
        print("State cleared.")
        return
    cfg = load_config()
    if cmd == "test-telegram":
        print("sent" if notify(cfg, "Test message from grade watcher ✅") else "failed")
    elif cmd == "chat-id":
        cmd_chat_id(cfg)
    elif cmd == "inspect":
        cmd_inspect(cfg)
    elif cmd == "check":
        cmd_check(cfg)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()