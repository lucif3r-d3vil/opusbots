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

from shared.qbittorrent import QBitError, build_base_url, split_host_port

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.json")

# Nothing here points at a real server on purpose: the Telegram token, the
# qBittorrent address and the media paths are all entered in the web panel and
# stored in config.json.  A hardcoded default host only ever produced
# confusing "cannot connect / auth failed" errors on a fresh install.
DEFAULT_CONFIG = {
    "telegram": {
        "bot_token": "",
        "allowed_user_id": 0,
    },
    "qbittorrent": {
        # Radarr-style: host and port are stored separately, e.g.
        # "192.168.1.50" + "30024".  A full URL in "host" also works.
        "host": "",
        "port": "",
        # Optional sub-path when qBittorrent sits behind a reverse proxy,
        # the same thing Radarr calls "URL Base" (e.g. "/qbittorrent").
        "url_base": "",
        "user": "",
        "pass": "",
        # Set to false for self-signed certificates.
        "verify_tls": True,
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


def _normalize(cfg):
    """Apply in-place migrations/normalisation and return the config."""
    q = cfg.get("qbittorrent")
    if isinstance(q, dict):
        host = str(q.get("host") or "").strip()
        port = str(q.get("port") or "").strip()

        # Migration: older versions had a single "host" field holding a whole
        # URL such as "http://192.168.1.50:30024".  Split it so the web panel
        # can show Radarr-style Host and Port boxes.
        if host and not port:
            host_only, host_port = split_host_port(host)
            if host_port:
                host, port = host_only, host_port

        q["host"] = host
        q["port"] = port
        q["url_base"] = str(q.get("url_base") or "").strip()
        q["user"] = str(q.get("user") or "").strip()
        q["pass"] = str(q.get("pass") or "")
    return cfg


def get_bot_token(cfg):
    """
    Get the configured bot token, falling back to legacy token fields
    if migrating from a previous 3-bot configuration.
    """
    tg = cfg.get("telegram", {})
    token = str(tg.get("bot_token", "") or "").strip()
    if token:
        return token
    # Legacy fallbacks:
    for legacy_key in ["mirror_bot_token", "downloads_bot_token", "music_bot_token"]:
        legacy_token = str(tg.get(legacy_key, "") or "").strip()
        if legacy_token:
            return legacy_token
    return ""


def get_allowed_user_id(cfg):
    """Get the authorized Telegram user ID."""
    try:
        return int(cfg.get("telegram", {}).get("allowed_user_id", 0))
    except (ValueError, TypeError):
        return 0


def get_qbit_summary(cfg):
    """Short, secret-free description of the qBittorrent address the bot will use."""
    q = cfg.get("qbittorrent", {}) or {}
    try:
        return build_base_url(q.get("host"), q.get("port"), q.get("url_base"))
    except QBitError:
        return "not configured"


def load_config():
    """Read config.json, creating it with defaults if missing/corrupt."""
    with _lock:
        if not os.path.exists(CONFIG_PATH):
            defaults = json.loads(json.dumps(DEFAULT_CONFIG))
            _write(defaults)
            return defaults
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = _deep_merge(DEFAULT_CONFIG, data)

            # Auto-migrate legacy tokens if bot_token is empty
            if not merged["telegram"].get("bot_token"):
                legacy_token = get_bot_token(merged)
                if legacy_token:
                    merged["telegram"]["bot_token"] = legacy_token

            return _normalize(merged)
        except Exception as e:
            print(f"config load error, using defaults: {e}")
            return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    """Save config dictionary atomically."""
    with _lock:
        merged = _normalize(_deep_merge(DEFAULT_CONFIG, cfg))
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
