"""
Unified System and Media Status Handler for OpusBots.
Aggregates storage statistics, qBittorrent downloads, video rendering tasks,
and background music queues into an informative, real-time dashboard.
"""

import time
from bots import music_handler, torrent_handler, video_handler
from shared import tgbot
from shared.utils import escape_html, format_eta, format_size, format_speed, get_disk_usage, progress_bar


def build_status_keyboard():
    """Build interactive action buttons for the status dashboard."""
    rows = [
        [
            {"text": "🔄 Refresh", "callback_data": "status:refresh"},
            {"text": "📜 Torrents", "callback_data": "status:torrents"},
        ],
        [
            {"text": "⏸️ Pause Torrents", "callback_data": "status:pause_all"},
            {"text": "▶️ Resume Torrents", "callback_data": "status:resume_all"},
        ],
    ]
    return tgbot.inline_keyboard(rows)


def build_status_text(cfg):
    """Generate comprehensive HTML status report."""
    lines = ["<b>⚡ OpusBots Unified Dashboard</b>", ""]

    # 1. Storage & Disks
    lines.append("<b>💾 Storage Status:</b>")
    paths = cfg.get("paths", {})

    disk_items = [
        ("Torrents", paths.get("downloads_completed", "/tank/Downloads/Completed")),
        ("Movies", paths.get("movies", "/tank/Movies")),
        ("Music", paths.get("music", "/tank/Music")),
    ]

    for label, path in disk_items:
        usage = get_disk_usage(path)
        if usage["available"]:
            lines.append(
                f"• <b>{label}</b>: [{usage['bar']}] {usage['used_pct']}%\n"
                f"  <code>{usage['free_gb']:.1f} GB free / {usage['total_gb']:.1f} GB</code>"
            )
        else:
            lines.append(f"• <b>{label}</b>: <i>path unavailable</i> (<code>{escape_html(path)}</code>)")
    lines.append("")

    # 2. qBittorrent Downloads
    lines.append("<b>🧲 qBittorrent:</b>")
    try:
        torrents = torrent_handler.get_torrents(cfg)
        downloading = [t for t in torrents if t.get("state") in ["downloading", "stalledDL", "forcedDL"]]
        seeding = [t for t in torrents if t.get("state") in ["uploading", "stalledUP", "forcedUP"]]

        lines.append(f"• Total: <b>{len(torrents)}</b> | Active: <b>{len(downloading)}</b> | Seeding: <b>{len(seeding)}</b>")

        if downloading:
            for t in downloading[:3]:
                name = escape_html(t.get("name", "Unknown")[:35])
                prog = t.get("progress", 0.0) * 100.0
                bar = progress_bar(prog, width=6)
                spd = format_speed(t.get("dlspeed", 0))
                eta = format_eta(t.get("eta", 8640000))
                lines.append(f"  ▪ <b>{name}</b>\n    [{bar}] {prog:.1f}% • {spd} • ETA: {eta}")
            if len(downloading) > 3:
                lines.append(f"  <i>... +{len(downloading) - 3} more active</i>")
    except Exception as e:
        lines.append(f"• <i>Status offline: {escape_html(str(e)[:50])}</i>")
    lines.append("")

    # 3. Video / Movie Downloads
    active_vids = video_handler.get_active_downloads()
    lines.append("<b>🎬 Movie / Video Downloads:</b>")
    if active_vids:
        for did, v in active_vids.items():
            elapsed = int(time.time() - v.get("started", time.time()))
            mins, secs = divmod(elapsed, 60)
            lines.append(
                f"• <b>{escape_html(v.get('title', 'Video')[:35])}</b>\n"
                f"  Quality: {v.get('res', 'Best')} • Running: {mins}m {secs:02d}s"
            )
    else:
        lines.append("• <i>No active video downloads</i>")
    lines.append("")

    # 4. Music Downloads & Queue
    m_status = music_handler.get_music_status()
    lines.append("<b>🎵 Music Queue:</b>")
    if m_status["is_downloading"] and m_status["active_job"]:
        job = m_status["active_job"]
        title = escape_html(job.get("title", "Track")[:35])
        pct = job.get("percent", 0.0)
        bar = progress_bar(pct, width=6)
        spd = job.get("speed", "")
        lines.append(f"• Downloading: <b>{title}</b>\n  [{bar}] {pct:.1f}% {spd}")
    elif m_status["is_downloading"]:
        lines.append("• <i>Downloading in progress...</i>")
    else:
        lines.append("• <i>Music worker idle</i>")

    if m_status["queue_size"] > 0:
        lines.append(f"• Pending in queue: <b>{m_status['queue_size']}</b> items")

    lines.append(f"\n<i>Updated: {time.strftime('%H:%M:%S UTC', time.gmtime())}</i>")
    return "\n".join(lines)


def get_torrents_overview(cfg, active_only=False):
    """Fetch and format torrents overview."""
    try:
        torrents = torrent_handler.get_torrents(cfg, filter_mode="downloading" if active_only else None)
        return torrent_handler.format_torrents_status(torrents, active_only=active_only)
    except Exception as e:
        return f"❌ <b>qBittorrent Error:</b>\n<code>{escape_html(str(e))}</code>"
