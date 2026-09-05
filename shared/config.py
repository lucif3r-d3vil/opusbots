"""
Shared config store for OpusBots.

Config lives in a single JSON file (default /config/config.json, shared via a
Docker volume between the bot container and the config-web container).
Bots call load_config() at the top of message handlers so changes made in the
web UI take effect without a restart.
"""

import json
import os
import threading

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.json")

DEFAULT_CONFIG = {
    "telegram": {
        "bot_token": "",
        "allowed_user_id": 0,
    },
    "qbittorrent": {
        "host": "http://192.168.1.50:30024",
        "user": "",
        "pass": "",
    },
    "paths": {
        "downloads_completed": "/tank/Downloads/Completed",
        "movies": "/tank/Movies",
        "music": "/tank/Music",
    },
}

_lock = threading.Lock()


def _deep_merge(default, override):
    result = dict(default)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def get_bot_token(cfg):
    """
    Get the configured bot token, falling back to legacy token fields
    if migrating from a previous 3-bot configuration.
    """
    tg = cfg.get("telegram", {})
    token = tg.get("bot_token", "").strip()
    if token:
        return token
    # Legacy fallbacks:
    for legacy_key in ["mirror_bot_token", "downloads_bot_token", "music_bot_token"]:
        legacy_token = tg.get(legacy_key, "").strip()
        if legacy_token:
            return legacy_token
    return ""


def get_allowed_user_id(cfg):
    """Get the authorized Telegram user ID."""
    try:
        return int(cfg.get("telegram", {}).get("allowed_user_id", 0))
    except (ValueError, TypeError):
        return 0


def load_config():
    """Read config.json, creating it with defaults if missing/corrupt."""
    with _lock:
        if not os.path.exists(CONFIG_PATH):
            _write(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = _deep_merge(DEFAULT_CONFIG, data)

            # Auto-migrate legacy tokens if bot_token is empty
            if not merged["telegram"].get("bot_token"):
                legacy_token = get_bot_token(merged)
                if legacy_token:
                    merged["telegram"]["bot_token"] = legacy_token

            return merged
        except Exception as e:
            print(f"config load error, using defaults: {e}")
            return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    """Save config dictionary atomically."""
    with _lock:
        merged = _deep_merge(DEFAULT_CONFIG, cfg)
        _write(merged)
        return merged


def _write(cfg):
    target_dir = os.path.dirname(CONFIG_PATH)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
