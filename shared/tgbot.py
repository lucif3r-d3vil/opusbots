"""
Shared Telegram Bot API helpers + a generic long-polling loop.

Every bot passes a get_token(cfg) function so the loop always uses whatever
token is currently in config.json (edited live via the config-web UI). If the
token changes mid-run, we reset the update offset since offsets are
per-bot-token on Telegram's side.
"""

import json
import time

import requests

from shared.config import load_config


def _api(token, method):
    return f"https://api.telegram.org/bot{token}/{method}"


def send(token, chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(_api(token, "sendMessage"), json=payload, timeout=10)
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"send error: {e}")
        return None


def edit_message(token, chat_id, message_id, text):
    try:
        requests.post(_api(token, "editMessageText"), json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        print(f"edit error: {e}")


def answer_callback(token, callback_id, text=""):
    try:
        requests.post(_api(token, "answerCallbackQuery"), json={
            "callback_query_id": callback_id,
            "text": text,
        }, timeout=10)
    except Exception as e:
        print(f"answer_callback error: {e}")


def send_chat_action(token, chat_id, action="typing"):
    try:
        requests.post(_api(token, "sendChatAction"), json={
            "chat_id": chat_id, "action": action,
        }, timeout=10)
    except Exception as e:
        print(f"chat_action error: {e}")


def inline_keyboard(rows):
    return {"inline_keyboard": rows}


def download_file(token, file_id, dest_dir="/tmp"):
    r = requests.get(_api(token, "getFile"), params={"file_id": file_id}, timeout=15)
    file_path = r.json()["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    import os
    fname = os.path.basename(file_path)
    local = os.path.join(dest_dir, fname)
    with requests.get(file_url, stream=True, timeout=60) as resp:
        with open(local, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
    return local, fname


def get_updates(token, offset, timeout=30):
    r = requests.get(_api(token, "getUpdates"), params={
        "offset": offset, "timeout": timeout,
    }, timeout=timeout + 10)
    return r.json().get("result", [])


def run_polling(get_token, process_fn, bot_name="bot"):
    """
    Generic long-poll loop.

    get_token(cfg)     -> current bot token string (may change over time)
    process_fn(update, cfg, token) -> handle one Telegram update
    """
    last_id = 0
    last_token = None
    print(f"{bot_name} starting...")

    while True:
        try:
            cfg = load_config()
            token = get_token(cfg)

            if not token:
                print(f"{bot_name}: no token configured yet, waiting...")
                time.sleep(10)
                continue

            if token != last_token:
                last_id = 0  # offsets aren't portable across different bot tokens
                last_token = token
                print(f"{bot_name}: (re)connecting with current token")

            updates = get_updates(token, last_id + 1)
            for update in updates:
                last_id = update["update_id"]
                cfg = load_config()  # reload in case it changed mid-batch
                token = get_token(cfg) or token
                try:
                    process_fn(update, cfg, token)
                except Exception as e:
                    print(f"{bot_name} process error: {e}")

        except Exception as e:
            print(f"{bot_name} loop error: {e}")
            time.sleep(5)
