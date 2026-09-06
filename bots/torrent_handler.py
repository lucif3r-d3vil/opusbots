"""
Torrent and Magnet handler integrating with qBittorrent Web API v2.

Supports magnet links, HTTP torrent URLs, .torrent file uploads, category
routing, and live status tracking.  All transport, authentication and version
compatibility live in :mod:`shared.qbittorrent`; this module is the
Telegram-facing layer on top of it.
"""

import re

from shared import qbittorrent
from shared.qbittorrent import (
    QBitError,
    error_text,
)
from shared.utils import escape_html, format_eta, format_size, format_speed, progress_bar

# Re-exported so callers (config-web, tests) keep a single import point.
test_qbit_connection = qbittorrent.test_connection
diagnose_connection = qbittorrent.diagnose

TV_PATTERNS = [
    r's\d{1,2}e\d{1,2}',
    r's\d{1,2}',
    r'season[\s\._\-]?\d+',
    r'episode[\s\._\-]?\d+',
    r'complete[\s\._\-]series',
    r'batch',
]


def client(cfg, force_fresh=False):
    """Return the shared, authenticated qBittorrent client for ``cfg``."""
    return qbittorrent.client_for(cfg, force_fresh=force_fresh)


def qbit_session(cfg):
    """Authenticate with qBittorrent and return an active requests.Session.

    Kept for backwards compatibility.  The session is cached per credential set
    so callers no longer trigger a fresh login -- and a fresh qBittorrent
    "too many failed attempts" IP ban -- on every single API call.
    """
    qbit = client(cfg)
    qbit.login()
    return qbit.session


def detect_category(text):
    """Heuristic to detect whether a torrent is a TV Show (Sonarr) or Movie (Radarr)."""
    lower = (text or "").lower()
    for pattern in TV_PATTERNS:
        if re.search(pattern, lower):
            return "tv-sonarr", "📺 TV Show (Sonarr)"
    return "radarr", "🎬 Movie (Radarr)"


def add_torrent(cfg, source, category=None, filename=None):
    """Add a magnet link, a .torrent URL or raw .torrent bytes to qBittorrent.

    Torrents are routed purely by **category**: the save path is whatever the
    category is configured with in qBittorrent (or qBittorrent's own default
    when the category has none).  We deliberately do *not* send an explicit
    ``savepath`` anymore -- the panel's "Torrent Downloads" path is a host path
    that a containerized qBittorrent usually cannot see, and it would override
    the category's save path, breaking Radarr/Sonarr routing and AutoTMM.

    Returns a dict: ``{"ok", "category", "applied", "warning", "error"}`` where
    ``applied`` tells whether qBittorrent really got the category.  A category
    that does not exist yet makes ``torrents/add`` answer "Fails."; we create
    the category and retry once rather than dropping the torrent into the
    default folder.
    """
    q = cfg.get("qbittorrent", {})
    is_file = filename is not None

    if category is None:
        category, _ = detect_category(filename if is_file else source)

    result = {"ok": False, "category": category, "applied": True, "warning": "", "error": ""}
    qbit = client(cfg)

    def _add(cat):
        if is_file:
            return qbit.add_torrent_files(source, filename, category=cat or None)
        return qbit.add_urls(source, category=cat or None)

    try:
        if _add(category):
            result["ok"] = True
            return result

        if category:
            # "Fails." almost always means the category does not exist in
            # qBittorrent yet.  Create it and retry once, so the torrent lands
            # where Radarr/Sonarr expect it instead of the default folder.
            try:
                if category not in qbit.categories():
                    qbit.create_category(category)
                if _add(category):
                    result["ok"] = True
                    return result
            except QBitError:
                pass  # fall through: add it without the category

            # Last resort -- qBittorrent's default save path applies.
            if _add(""):
                result.update({
                    "ok": True,
                    "applied": False,
                    "warning": (
                        f"qBittorrent refused the category '{category}', so the torrent was "
                        f"added without one. Create the '{category}' category in qBittorrent "
                        "(Categories tab, with its save path) so Radarr/Sonarr can pick it up."
                    ),
                })
                return result

        result["error"] = (
            f"qBittorrent rejected the torrent (HTTP response was not 'Ok.'). "
            f"Check that {q.get('host', 'the host')} is the Web UI port and that qBittorrent's "
            f"default save path (Tools > Options > Downloads) exists inside the qBittorrent container."
        )
        return result
    except QBitError as exc:
        result["error"] = error_text(exc)
        return result


def add_magnet(cfg, magnet_or_url, category=None):
    """Add a magnet link or HTTP torrent link to qBittorrent."""
    return add_torrent(cfg, magnet_or_url, category=category)["ok"]


def add_torrent_file(cfg, file_bytes, filename, category=None):
    """Upload a .torrent file directly to qBittorrent."""
    return add_torrent(cfg, file_bytes, category=category, filename=filename)["ok"]


def get_torrents(cfg, filter_mode=None):
    """Retrieve list of torrents from qBittorrent."""
    return client(cfg).torrents_info(status_filter=filter_mode)


def set_torrent_state(cfg, start, hashes="all"):
    """Start (True) or stop (False) torrents. Works on qBittorrent 4.x and 5.x."""
    return client(cfg).set_torrent_state(start, hashes=hashes)


def pause_torrents(cfg, hashes="all"):
    """Pause/stop all or specific torrents."""
    return set_torrent_state(cfg, start=False, hashes=hashes)


def resume_torrents(cfg, hashes="all"):
    """Resume/start all or specific torrents."""
    return set_torrent_state(cfg, start=True, hashes=hashes)


# qBittorrent 5.x renamed these endpoints; keep the modern names available too.
stop_torrents = pause_torrents
start_torrents = resume_torrents


def get_versions(cfg):
    """Return (app_version, web_api_version) for the configured qBittorrent."""
    return client(cfg).fetch_versions()


def is_torrent_or_magnet(text):
    """Check if text is a magnet link or .torrent URL."""
    clean = (text or "").strip()
    return clean.startswith("magnet:?") or (
        (clean.startswith("http://") or clean.startswith("https://")) and ".torrent" in clean.lower()
    )


def is_active_state(state):
    """True for torrent states that mean 'working on a download' (v4 + v5)."""
    return state in qbittorrent.DOWNLOADING_STATES


def is_seeding_state(state):
    return state in qbittorrent.SEEDING_STATES


def is_stopped_state(state):
    return state in qbittorrent.STOPPED_STATES


def format_torrents_status(torrents, active_only=False):
    """Format torrent list into rich HTML message for Telegram."""
    if not torrents:
        return "<i>No active torrents.</i>" if active_only else "<i>No torrents found in qBittorrent.</i>"

    lines = []
    lines.append(f"<b>{'Active Downloads' if active_only else 'Torrents Overview'} ({len(torrents)}):</b>\n")

    for t in torrents[:10]:
        name = escape_html(str(t.get("name", "Unknown"))[:45])
        try:
            progress = float(t.get("progress", 0.0)) * 100.0
        except (TypeError, ValueError):
            progress = 0.0
        bar = progress_bar(progress, width=8)
        size_str = format_size(t.get("size", 0))
        state = str(t.get("state", "unknown"))
        dl_speed = format_speed(t.get("dlspeed", 0))
        eta_str = format_eta(t.get("eta", 8640000))

        cat = t.get("category", "")
        cat_badge = f" [<code>{escape_html(cat)}</code>]" if cat else ""

        lines.append(f"• <b>{name}</b>{cat_badge}")
        if active_only or dl_speed != "0 B/s":
            lines.append(f"  [{bar}] {progress:.1f}% • {size_str} • {dl_speed} • ETA: {eta_str}")
        else:
            lines.append(f"  [{bar}] {progress:.1f}% • {size_str} • State: <i>{escape_html(state)}</i>")
        lines.append("")

    if len(torrents) > 10:
        lines.append(f"<i>... and {len(torrents) - 10} more torrents</i>")

    return "\n".join(lines)
