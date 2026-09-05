"""
Torrent and Magnet handler integrating with qBittorrent Web API v2.
Supports magnet links, HTTP torrent URLs, .torrent file uploads, category routing,
and live status tracking.
"""

import re
import requests
from shared import tgbot
from shared.utils import escape_html, format_eta, format_size, format_speed, progress_bar


def qbit_session(cfg):
    """Authenticate with qBittorrent and return an active requests.Session."""
    q = cfg.get("qbittorrent", {})
    host = q.get("host", "").rstrip("/")
    user = q.get("user", "")
    password = q.get("pass", "")

    if not host:
        raise ValueError("qBittorrent host is not configured.")

    s = requests.Session()
    try:
        r = s.post(f"{host}/api/v2/auth/login", data={
            "username": user,
            "password": password,
        }, timeout=10)
    except Exception as e:
        raise ConnectionError(f"Could not connect to qBittorrent at {host}: {e}")

    if r.text.strip() != "Ok.":
        raise PermissionError("qBittorrent authentication failed. Check username and password.")
    return s


def test_qbit_connection(cfg):
    """Test qBittorrent connection and return (success: bool, message: str)."""
    try:
        s = qbit_session(cfg)
        host = cfg["qbittorrent"]["host"].rstrip("/")
        ver_r = s.get(f"{host}/api/v2/app/version", timeout=10)
        api_ver_r = s.get(f"{host}/api/v2/app/webapiVersion", timeout=10)
        qbit_ver = ver_r.text.strip() if ver_r.status_code == 200 else "Unknown"
        api_ver = api_ver_r.text.strip() if api_ver_r.status_code == 200 else "v2"
        return True, f"Connected to qBittorrent {qbit_ver} (WebAPI {api_ver})"
    except Exception as e:
        return False, str(e)


def detect_category(text):
    """Heuristic to detect whether a torrent is a TV Show (Sonarr) or Movie (Radarr)."""
    lower = text.lower()
    tv_patterns = [
        r's\d{1,2}e\d{1,2}',
        r's\d{1,2}',
        r'season[\s\._\-]?\d+',
        r'episode[\s\._\-]?\d+',
        r'complete[\s\._\-]series',
        r'batch',
    ]
    for pattern in tv_patterns:
        if re.search(pattern, lower):
            return "tv-sonarr", "📺 TV Show (Sonarr)"
    return "radarr", "🎬 Movie (Radarr)"


def add_magnet(cfg, magnet_or_url, category=None):
    """Add a magnet link or HTTP torrent link to qBittorrent."""
    q = cfg["qbittorrent"]
    host = q["host"].rstrip("/")
    savepath = cfg["paths"]["downloads_completed"]
    if category is None:
        category, _ = detect_category(magnet_or_url)

    s = qbit_session(cfg)
    r = s.post(f"{host}/api/v2/torrents/add", data={
        "urls": magnet_or_url,
        "savepath": savepath,
        "category": category,
    }, timeout=15)
    return r.text.strip() == "Ok."


def add_torrent_file(cfg, file_bytes, filename, category=None):
    """Upload a .torrent file directly to qBittorrent."""
    q = cfg["qbittorrent"]
    host = q["host"].rstrip("/")
    savepath = cfg["paths"]["downloads_completed"]
    if category is None:
        category, _ = detect_category(filename)

    s = qbit_session(cfg)
    files = {
        "torrents": (filename, file_bytes, "application/x-bittorrent"),
    }
    data = {
        "savepath": savepath,
        "category": category,
    }
    r = s.post(f"{host}/api/v2/torrents/add", files=files, data=data, timeout=20)
    return r.text.strip() == "Ok."


def get_torrents(cfg, filter_mode=None):
    """Retrieve list of torrents from qBittorrent."""
    q = cfg["qbittorrent"]
    host = q["host"].rstrip("/")
    s = qbit_session(cfg)
    url = f"{host}/api/v2/torrents/info"
    if filter_mode:
        url += f"?filter={filter_mode}"
    r = s.get(url, timeout=15)
    return r.json()


def pause_torrents(cfg, hashes="all"):
    """Pause all or specific torrents."""
    q = cfg["qbittorrent"]
    host = q["host"].rstrip("/")
    s = qbit_session(cfg)
    r = s.post(f"{host}/api/v2/torrents/pause", data={"hashes": hashes}, timeout=10)
    return r.status_code == 200


def resume_torrents(cfg, hashes="all"):
    """Resume all or specific torrents."""
    q = cfg["qbittorrent"]
    host = q["host"].rstrip("/")
    s = qbit_session(cfg)
    r = s.post(f"{host}/api/v2/torrents/resume", data={"hashes": hashes}, timeout=10)
    return r.status_code == 200


def is_torrent_or_magnet(text):
    """Check if text is a magnet link or .torrent URL."""
    clean = text.strip()
    return clean.startswith("magnet:?") or (
        (clean.startswith("http://") or clean.startswith("https://")) and ".torrent" in clean.lower()
    )


def format_torrents_status(torrents, active_only=False):
    """Format torrent list into rich HTML message for Telegram."""
    if not torrents:
        return "<i>No active torrents.</i>" if active_only else "<i>No torrents found in qBittorrent.</i>"

    lines = []
    lines.append(f"<b>{'Active Downloads' if active_only else 'Torrents Overview'} ({len(torrents)}):</b>\n")

    for t in torrents[:10]:
        name = escape_html(t.get("name", "Unknown")[:45])
        progress = t.get("progress", 0.0) * 100.0
        bar = progress_bar(progress, width=8)
        size_str = format_size(t.get("size", 0))
        state = t.get("state", "unknown")
        dl_speed = format_speed(t.get("dlspeed", 0))
        eta_sec = t.get("eta", 8640000)
        eta_str = format_eta(eta_sec)

        cat = t.get("category", "")
        cat_badge = f" [<code>{escape_html(cat)}</code>]" if cat else ""

        lines.append(f"• <b>{name}</b>{cat_badge}")
        if active_only or dl_speed != "0 B/s":
            lines.append(f"  [{bar}] {progress:.1f}% • {size_str} • {dl_speed} • ETA: {eta_str}")
        else:
            lines.append(f"  [{bar}] {progress:.1f}% • {size_str} • State: <i>{state}</i>")
        lines.append("")

    if len(torrents) > 10:
        lines.append(f"<i>... and {len(torrents) - 10} more torrents</i>")

    return "\n".join(lines)
