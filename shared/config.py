"""
Shared config store for all HomeLab Telegram bots.

Config lives in a single JSON file (default /config/config.json, shared via a
Docker volume between every bot container and the config-web container).
Bots call load_config() at the top of every loop iteration / message handler
so changes made in the web UI take effect without a restart.
"""

import json
import os
import threading

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.json")

DEFAULT_CONFIG = {
    "telegram": {
        "mirror_bot_token": "",
        "downloads_bot_token": "",
        "music_bot_token": "",
        "allowed_user_id": 0,
    },
    "qbittorrent": {
        "host": "http://192.168.1.50:30024",
        "user": "",
        "pass": "",
    },
    "paths": {
        "downloads_completed": "/mnt/tank/Downloads/Completed",
        "movies": "/mnt/tank/Movies",
        "tv": "/mnt/tank/TV",
        "music": "/mnt/tank/Music",
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


def load_config():
    """Read config.json, creating it with defaults if missing/corrupt."""
    with _lock:
        if not os.path.exists(CONFIG_PATH):
            _write(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            return _deep_merge(DEFAULT_CONFIG, data)
        except Exception as e:
            print(f"config load error, using defaults: {e}")
            return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    with _lock:
        merged = _deep_merge(DEFAULT_CONFIG, cfg)
        _write(merged)
        return merged


def _write(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
