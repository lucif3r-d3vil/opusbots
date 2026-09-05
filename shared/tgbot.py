"""
Shared Telegram Bot API helpers and long-polling engine.

Handles messaging, inline keyboards, callbacks, file downloads, token verification,
and error-resilient long polling.
"""

import json
import os
import time
import requests

from shared.config import load_config


def _api(token, method):
    return f"https://api.telegram.org/bot{token}/{method}"


def send(token, chat_id, text, reply_markup=None, parse_mode="HTML", disable_web_page_preview=True):
    """Send a message to a Telegram chat."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup
    try:
        r = requests.post(_api(token, "sendMessage"), json=payload, timeout=12)
        res = r.json()
        if not res.get("ok"):
            print(f"Telegram sendMessage failed: {res.get('description')}")
            # If HTML parsing fails, retry once with plain text as fallback
            if parse_mode == "HTML" and "can't parse entities" in res.get("description", "").lower():
                payload["parse_mode"] = None
                r2 = requests.post(_api(token, "sendMessage"), json=payload, timeout=12)
                return r2.json().get("result", {}).get("message_id")
        return res.get("result", {}).get("message_id")
    except Exception as e:
        print(f"send error: {e}")
        return None


def edit_message(token, chat_id, message_id, text, reply_markup=None, parse_mode="HTML", disable_web_page_preview=True):
    """Edit an existing message."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup
    try:
        r = requests.post(_api(token, "editMessageText"), json=payload, timeout=12)
        res = r.json()
        if not res.get("ok"):
            # Ignore "message is not modified" errors
            desc = res.get("description", "")
            if "message is not modified" not in desc.lower():
                print(f"Telegram editMessageText failed: {desc}")
                # Fallback if HTML parse error
                if parse_mode == "HTML" and "can't parse entities" in desc.lower():
                    payload["parse_mode"] = None
                    requests.post(_api(token, "editMessageText"), json=payload, timeout=12)
    except Exception as e:
        print(f"edit error: {e}")


def delete_message(token, chat_id, message_id):
    """Delete a message."""
    try:
        requests.post(_api(token, "deleteMessage"), json={
            "chat_id": chat_id,
            "message_id": message_id,
        }, timeout=10)
    except Exception as e:
        print(f"delete error: {e}")


def answer_callback(token, callback_id, text="", show_alert=False):
    """Acknowledge a callback query from an inline keyboard button."""
    try:
        requests.post(_api(token, "answerCallbackQuery"), json={
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": show_alert,
        }, timeout=10)
    except Exception as e:
        print(f"answer_callback error: {e}")


def send_chat_action(token, chat_id, action="typing"):
    """
    Send a chat action indicator.
    Valid actions: 'typing', 'upload_document', 'upload_video', 'record_audio', etc.
    """
    try:
        requests.post(_api(token, "sendChatAction"), json={
            "chat_id": chat_id,
            "action": action,
        }, timeout=10)
    except Exception as e:
        print(f"chat_action error: {e}")


def inline_keyboard(rows):
    """Build an inline keyboard markup dictionary."""
    return {"inline_keyboard": rows}


def get_file_info(token, file_id):
    """Get file information from Telegram API."""
    r = requests.get(_api(token, "getFile"), params={"file_id": file_id}, timeout=15)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Failed to retrieve file info"))
    return data["result"]


def get_file_bytes(token, file_id):
    """Download file bytes directly into memory."""
    info = get_file_info(token, file_id)
    file_path = info["file_path"]
    file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    resp = requests.get(file_url, timeout=60)
    resp.raise_for_status()
    return resp.content, os.path.basename(file_path)


def download_file(token, file_id, dest_dir="/tmp"):
    """Download a file from Telegram servers and save to disk."""
    os.makedirs(dest_dir, exist_ok=True)
    info = get_file_info(token, file_id)
    file_path = info["file_path"]
    file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    fname = os.path.basename(file_path)
    local = os.path.join(dest_dir, fname)
    with requests.get(file_url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(local, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
    return local, fname


def get_me(token):
    """
    Test Telegram bot token and fetch bot info.
    Returns (True, bot_info_dict) or (False, error_message).
    """
    if not token or not token.strip():
        return False, "Token is empty"
    try:
        r = requests.get(_api(token.strip(), "getMe"), timeout=10)
        data = r.json()
        if data.get("ok"):
            return True, data.get("result", {})
        return False, data.get("description", "Invalid token")
    except Exception as e:
        return False, str(e)


def get_updates(token, offset, timeout=30):
    """Poll updates from Telegram API."""
    try:
        r = requests.get(_api(token, "getUpdates"), params={
            "offset": offset,
            "timeout": timeout,
        }, timeout=timeout + 15)
        data = r.json()
        if data.get("ok"):
            return data.get("result", [])
        print(f"getUpdates returned not ok: {data.get('description')}")
        return []
    except Exception as e:
        print(f"getUpdates network error: {e}")
        return []


def run_polling(get_token, process_fn, bot_name="OpusBot", stop_event=None):
    """
    Generic long-polling loop.

    get_token(cfg) -> current bot token string
    process_fn(update, cfg, token) -> handle single update
    stop_event -> optional threading.Event to stop loop cleanly
    """
    last_id = 0
    last_token = None
    print(f"[{bot_name}] Starting unified Telegram bot engine...")

    while stop_event is None or not stop_event.is_set():
        try:
            cfg = load_config()
            token = get_token(cfg)

            if not token:
                print(f"[{bot_name}] No bot token configured yet. Waiting in idle loop...")
                time.sleep(10)
                continue

            if token != last_token:
                last_id = 0  # offsets are per-bot-token
                last_token = token
                print(f"[{bot_name}] Connected with bot token (***{token[-6:] if len(token) > 6 else ''})")

            updates = get_updates(token, last_id + 1)
            for update in updates:
                last_id = update["update_id"]
                cfg = load_config()  # reload in case config changed
                curr_token = get_token(cfg) or token
                try:
                    process_fn(update, cfg, curr_token)
                except Exception as e:
                    print(f"[{bot_name}] Handler error: {e}")

        except Exception as e:
            print(f"[{bot_name}] Polling loop error: {e}")
            time.sleep(5)
