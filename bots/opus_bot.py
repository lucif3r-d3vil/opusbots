"""
OpusBots - Unified Telegram Bot for Media Automation, Downloads, and Homelab Workflows.

Integrates Torrent Mirroring (qBittorrent), Movie/Video Downloads (yt-dlp + uploads),
and Music & Playlist Downloads (MP3/FLAC + background queue) into a single, cohesive bot.
"""

import os
import time
import uuid

from bots import music_handler, status_handler, torrent_handler, video_handler
from shared import tgbot
from shared.config import get_allowed_user_id, get_bot_token
from shared.qbittorrent import error_text
from shared.utils import escape_html, get_disk_usage

# Cache for interactive link choices
# {link_id: {"url": str, "timestamp": float}}
pending_media_links = {}


def clean_expired_links():
    """Remove interactive link choices older than 1 hour."""
    now = time.time()
    expired = [k for k, v in pending_media_links.items() if now - v.get("timestamp", 0) > 3600]
    for k in expired:
        pending_media_links.pop(k, None)


def check_auth(update, cfg):
    """Check if sender is authorized. Returns (is_authorized: bool, user_id: int, chat_id: int)."""
    user_id = 0
    chat_id = 0

    if "message" in update:
        user_id = update["message"].get("from", {}).get("id", 0)
        chat_id = update["message"].get("chat", {}).get("id", 0)
    elif "callback_query" in update:
        user_id = update["callback_query"].get("from", {}).get("id", 0)
        chat_id = update["callback_query"].get("message", {}).get("chat", {}).get("id", 0)

    allowed_id = get_allowed_user_id(cfg)
    if allowed_id == 0:
        # No user ID configured yet; allow but remind admin
        return True, user_id, chat_id

    return (user_id == allowed_id), user_id, chat_id


def build_help_keyboard():
    """Build interactive help buttons."""
    return tgbot.inline_keyboard([
        [
            {"text": "🧲 Torrents Guide", "callback_data": "help:torrents"},
            {"text": "🎬 Movies Guide", "callback_data": "help:movies"},
        ],
        [
            {"text": "🎵 Music Guide", "callback_data": "help:music"},
            {"text": "📊 Dashboard", "callback_data": "status:refresh"},
        ],
    ])


def get_help_text(section="main"):
    """Return formatted help text for given section."""
    if section == "torrents":
        return (
            "<b>🧲 Torrents & qBittorrent Automation</b>\n\n"
            "<b>How to add torrents:</b>\n"
            "• Paste any <code>magnet:?xt=...</code> link directly into chat\n"
            "• Send an HTTP link ending in <code>.torrent</code>\n"
            "• Upload a <code>.torrent</code> file directly into chat\n\n"
            "<b>Commands:</b>\n"
            "• /torrents - View active and completed torrents\n"
            "• /downloading - View currently downloading torrents\n"
            "• /pause - Pause (stop) all torrents in qBittorrent\n"
            "• /resume - Resume (start) all torrents in qBittorrent\n"
            "• /qbit - Test the qBittorrent connection and show its version\n\n"
            "<b>Categories:</b>\n"
            "Torrents automatically route to <code>radarr</code> (Movies) or <code>tv-sonarr</code> (TV Shows)."
        )
    elif section == "movies":
        return (
            "<b>🎬 Movies & Video Downloads</b>\n\n"
            "<b>How to download videos:</b>\n"
            "• Paste any YouTube or supported video link to choose resolution\n"
            "• Use <code>/video &lt;URL&gt;</code> to download with quality picker\n"
            "• Upload any video file (MKV, MP4, AVI, etc.) to save directly to Movies\n\n"
            "<b>Commands:</b>\n"
            "• /video &lt;URL&gt; - Interactive video resolution selector\n"
            "• /status - View active video downloads and disk space"
        )
    elif section == "music":
        return (
            "<b>🎵 Music & Playlist Downloads</b>\n\n"
            "<b>Commands:</b>\n"
            "• <code>/yt &lt;URL&gt;</code> - Download song as 320kbps MP3\n"
            "• <code>/flac &lt;URL&gt;</code> - Download song as lossless FLAC\n"
            "• <code>/playlist &lt;URL&gt;</code> - Download complete YouTube playlist\n"
            "• <code>/search &lt;artist - song&gt;</code> - Search and download track\n\n"
            "<b>Features:</b>\n"
            "• Embedded high-resolution album artwork\n"
            "• Embedded ID3 metadata (Artist, Album, Title)\n"
            "• Background queue with live progress bars"
        )

    return (
        "<b>⚡ OpusBots Unified Bot</b>\n\n"
        "Your all-in-one Telegram bot for torrents, movies, and music automation.\n\n"
        "<b>Quick Actions:</b>\n"
        "• Send a <b>Magnet link</b> or <b>.torrent file</b> -> added to qBittorrent\n"
        "• Send a <b>YouTube link</b> -> interactive download picker (Audio/Video)\n"
        "• Upload a <b>Video / Audio file</b> -> saved straight to library\n\n"
        "<b>Commands:</b>\n"
        "• /status - Unified system & downloads dashboard\n"
        "• /torrents - Manage qBittorrent downloads\n"
        "• /qbit - Diagnose the qBittorrent connection\n"
        "• /video &lt;URL&gt; - Download video to Movies\n"
        "• /yt &lt;URL&gt; - Download MP3 audio\n"
        "• /flac &lt;URL&gt; - Download FLAC audio\n"
        "• /playlist &lt;URL&gt; - Download YouTube playlist\n"
        "• /search &lt;query&gt; - Search music and download\n"
        "• /paths - Storage and disk usage report\n"
        "• /help - Display this guide"
    )


def handle_callback(update, cfg, token):
    """Handle all inline keyboard callback queries."""
    cb = update["callback_query"]
    cb_id = cb["id"]
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    msg_id = msg.get("message_id")

    tgbot.answer_callback(token, cb_id)

    # 1. Navigation / Help
    if data.startswith("help:"):
        section = data.split(":")[1]
        text = get_help_text(section)
        rows = [
            [{"text": "🧲 Torrents", "callback_data": "help:torrents"}, {"text": "🎬 Movies", "callback_data": "help:movies"}],
            [{"text": "🎵 Music", "callback_data": "help:music"}, {"text": "🏠 Main Menu", "callback_data": "help:main"}],
        ]
        tgbot.edit_message(token, chat_id, msg_id, text, reply_markup=tgbot.inline_keyboard(rows))
        return

    # 2. Status Actions
    if data == "status:refresh":
        status_text = status_handler.build_status_text(cfg)
        tgbot.edit_message(token, chat_id, msg_id, status_text, reply_markup=status_handler.build_status_keyboard())
        return

    if data == "status:torrents":
        text = status_handler.get_torrents_overview(cfg, active_only=False)
        rows = [
            [{"text": "🔄 Refresh", "callback_data": "status:torrents"}, {"text": "📊 Full Status", "callback_data": "status:refresh"}],
            [{"text": "⏸️ Pause All", "callback_data": "status:pause_all"}, {"text": "▶️ Resume All", "callback_data": "status:resume_all"}],
        ]
        tgbot.edit_message(token, chat_id, msg_id, text, reply_markup=tgbot.inline_keyboard(rows))
        return

    if data in ("status:pause_all", "status:resume_all"):
        start = data == "status:resume_all"
        # The callback was already acknowledged above, so report through the chat.
        ok, message = set_torrents_running(token, chat_id, cfg, start=start)
        if not ok:
            tgbot.send(token, chat_id, message)
        status_text = status_handler.build_status_text(cfg)
        tgbot.edit_message(token, chat_id, msg_id, status_text, reply_markup=status_handler.build_status_keyboard())
        return

    # 3. Interactive URL Choices (MP3, FLAC, Video, Playlist)
    if data.startswith("choice:"):
        parts = data.split(":")
        choice_type = parts[1]
        link_id = parts[2]

        item = pending_media_links.get(link_id)
        if not item:
            tgbot.edit_message(token, chat_id, msg_id, "<i>Request expired. Please send the link again.</i>")
            return

        url = item["url"]

        if choice_type == "cancel":
            pending_media_links.pop(link_id, None)
            tgbot.edit_message(token, chat_id, msg_id, "❌ Cancelled.")
            return

        if choice_type == "mp3":
            tgbot.edit_message(token, chat_id, msg_id, "🎵 <b>Selected: MP3 Audio</b>\nAdding to download queue...")
            music_handler.enqueue_job(
                token, chat_id,
                lambda u=url, c=chat_id: music_handler.download_song(token, cfg, c, u, quality="mp3"),
                label="MP3 Song Download"
            )
            return

        if choice_type == "flac":
            tgbot.edit_message(token, chat_id, msg_id, "🎧 <b>Selected: FLAC Lossless Audio</b>\nAdding to download queue...")
            music_handler.enqueue_job(
                token, chat_id,
                lambda u=url, c=chat_id: music_handler.download_song(token, cfg, c, u, quality="flac"),
                label="FLAC Song Download"
            )
            return

        if choice_type == "playlist":
            tgbot.edit_message(token, chat_id, msg_id, "📋 <b>Selected: Full Playlist</b>\nAdding to download queue...")
            music_handler.enqueue_job(
                token, chat_id,
                lambda u=url, c=chat_id: music_handler.download_playlist(token, cfg, c, u, quality="mp3"),
                label="Playlist Download"
            )
            return

        if choice_type == "video":
            tgbot.edit_message(token, chat_id, msg_id, "🔍 <i>Analyzing available video resolutions...</i>")
            try:
                title, title_safe, formats, duration = video_handler.get_video_formats(url)
                if not formats:
                    tgbot.edit_message(token, chat_id, msg_id, "❌ No downloadable video streams found for this link.")
                    return

                query_id = str(uuid.uuid4())[:8]
                video_handler.pending_video_requests[query_id] = {
                    "url": url,
                    "title": title,
                    "title_safe": title_safe,
                    "formats": formats,
                    "chat_id": chat_id,
                }
                kb = video_handler.build_resolution_keyboard(formats, query_id)
                tgbot.edit_message(
                    token, chat_id, msg_id,
                    f"🎬 <b>{escape_html(title)}</b>\n⏱️ Duration: {escape_html(duration)}\n\nSelect video quality:",
                    reply_markup=kb,
                )
            except Exception as e:
                tgbot.edit_message(token, chat_id, msg_id, f"❌ Failed to extract video formats:\n<code>{escape_html(str(e)[:250])}</code>")
            return

    # 4. Video Resolution Selection
    if data.startswith("vcancel:"):
        query_id = data.split(":")[1]
        video_handler.pending_video_requests.pop(query_id, None)
        tgbot.edit_message(token, chat_id, msg_id, "❌ Video download cancelled.")
        return

    if data.startswith("vres:"):
        parts = data.split(":")
        query_id = parts[1]
        idx = int(parts[2])

        req = video_handler.pending_video_requests.pop(query_id, None)
        if not req or idx >= len(req["formats"]):
            tgbot.edit_message(token, chat_id, msg_id, "<i>Video selection expired. Please resend the link.</i>")
            return

        chosen_fmt = req["formats"][idx]
        video_handler.start_video_download(
            token=token,
            cfg=cfg,
            url=req["url"],
            fmt_id=chosen_fmt["id"],
            res_label=chosen_fmt["res"],
            title_safe=req["title_safe"],
            chat_id=chat_id,
            msg_id=msg_id,
            height=chosen_fmt.get("height"),
        )
        return


def handle_message(update, cfg, token):
    """Handle regular messages (commands, text links, uploaded files)."""
    msg = update["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id", 0)

    # Check for document or media upload
    if "document" in msg or "video" in msg or "audio" in msg:
        handle_media_upload(msg, cfg, token, chat_id)
        return

    text = msg.get("text", "").strip()
    if not text:
        return

    clean_expired_links()

    # Commands
    if text in ["/start", "/help"]:
        allowed_id = get_allowed_user_id(cfg)
        user_warning = ""
        if allowed_id == 0:
            user_warning = (
                f"\n\n⚠️ <b>Setup Warning:</b> Bot is not locked to a Telegram User ID.\n"
                f"Your User ID is: <code>{user_id}</code>\n"
                f"Set this in the Web Config (http://server:8090) to secure your bot."
            )
        tgbot.send(token, chat_id, get_help_text("main") + user_warning, reply_markup=build_help_keyboard())
        return

    if text in ["/status", "/dashboard"]:
        status_text = status_handler.build_status_text(cfg)
        tgbot.send(token, chat_id, status_text, reply_markup=status_handler.build_status_keyboard())
        return

    if text in ["/torrents", "/torrent"]:
        overview = status_handler.get_torrents_overview(cfg, active_only=False)
        tgbot.send(token, chat_id, overview)
        return

    if text == "/downloading":
        overview = status_handler.get_torrents_overview(cfg, active_only=True)
        tgbot.send(token, chat_id, overview)
        return

    if text in ["/pause", "/pause_all", "/stop_all"]:
        _, message = set_torrents_running(token, chat_id, cfg, start=False)
        tgbot.send(token, chat_id, message)
        return

    if text in ["/resume", "/resume_all", "/start_all"]:
        _, message = set_torrents_running(token, chat_id, cfg, start=True)
        tgbot.send(token, chat_id, message)
        return

    if text in ["/qbit", "/qbittorrent", "/testqbit"]:
        report_qbit_connection(token, chat_id, cfg)
        return

    if text == "/paths":
        paths = cfg.get("paths", {})
        lines = ["<b>📁 Configured Media Paths & Storage:</b>\n"]
        for label, p in [
            ("Downloads (Torrents)", paths.get("downloads_completed", "/tank/Downloads/Completed")),
            ("Movies", paths.get("movies", "/tank/Movies")),
            ("Music", paths.get("music", "/tank/Music")),
        ]:
            u = get_disk_usage(p)
            status_str = f"[{u['bar']}] {u['used_pct']}% used ({u['free_gb']:.1f} GB free / {u['total_gb']:.1f} GB)" if u["available"] else "<i>unavailable</i>"
            lines.append(f"• <b>{label}:</b>\n  <code>{escape_html(p)}</code>\n  {status_str}\n")
        tgbot.send(token, chat_id, "\n".join(lines))
        return

    if text == "/ping":
        tgbot.send(token, chat_id, "🏓 <b>Pong!</b> Bot is running and connected.")
        return

    # Direct Video Command
    if text == "/video" or text.startswith("/video "):
        url = text[len("/video"):].strip()
        if not url:
            tgbot.send(token, chat_id, "ℹ️ Usage: <code>/video &lt;URL&gt;</code> — or just paste a video link for the picker.")
            return
        msg_id = tgbot.send(token, chat_id, "🔍 <i>Analyzing available video resolutions...</i>")
        try:
            title, title_safe, formats, duration = video_handler.get_video_formats(url)
            if not formats:
                tgbot.edit_message(token, chat_id, msg_id, "❌ No downloadable video streams found for this link.")
                return

            query_id = str(uuid.uuid4())[:8]
            video_handler.pending_video_requests[query_id] = {
                "url": url,
                "title": title,
                "title_safe": title_safe,
                "formats": formats,
                "chat_id": chat_id,
            }
            kb = video_handler.build_resolution_keyboard(formats, query_id)
            tgbot.edit_message(
                token, chat_id, msg_id,
                f"🎬 <b>{escape_html(title)}</b>\n⏱️ Duration: {escape_html(duration)}\n\nSelect video quality:",
                reply_markup=kb,
            )
        except Exception as e:
            tgbot.edit_message(token, chat_id, msg_id, f"❌ Failed to extract video formats:\n<code>{escape_html(str(e)[:250])}</code>")
        return

    # Direct Music Commands
    music_commands = [("/yt", "mp3"), ("/mp3", "mp3"), ("/flac", "flac")]
    for prefix, quality in music_commands:
        if text != prefix and not text.startswith(prefix + " "):
            continue
        url = text[len(prefix):].strip()
        if not url:
            tgbot.send(token, chat_id, f"ℹ️ Usage: <code>{prefix} &lt;URL&gt;</code>")
            return
        label = "FLAC Song Download" if quality == "flac" else "MP3 Song Download"
        music_handler.enqueue_job(
            token, chat_id,
            lambda u=url, c=chat_id, q=quality: music_handler.download_song(token, cfg, c, u, quality=q),
            label=label,
        )
        return

    if text == "/playlist" or text.startswith("/playlist "):
        url = text[len("/playlist"):].strip()
        if not url:
            tgbot.send(token, chat_id, "ℹ️ Usage: <code>/playlist &lt;YouTube playlist URL&gt;</code>")
            return
        music_handler.enqueue_job(
            token, chat_id,
            lambda u=url, c=chat_id: music_handler.download_playlist(token, cfg, c, u, quality="mp3"),
            label="Playlist Download"
        )
        return

    if text == "/search" or text.startswith("/search "):
        query = text[len("/search"):].strip()
        if not query:
            tgbot.send(token, chat_id, "ℹ️ Usage: <code>/search &lt;artist - song&gt;</code>")
            return
        music_handler.enqueue_job(
            token, chat_id,
            lambda q=query, c=chat_id: music_handler.search_and_download(token, cfg, c, q, quality="mp3"),
            label=f"Search & Download: {query}"
        )
        return

    # Smart Magnet / Torrent Link Handling
    if torrent_handler.is_torrent_or_magnet(text):
        category, cat_label = torrent_handler.detect_category(text)
        tgbot.send_chat_action(token, chat_id, "typing")
        result = torrent_handler.add_torrent(cfg, text, category=category)
        if result["ok"]:
            destination = (
                "category save path in qBittorrent" if result["applied"] else "qBittorrent default save path"
            )
            body = (
                f"✅ <b>Added to qBittorrent!</b>\n\n"
                f"📂 Category: <b>{cat_label}</b> (<code>{escape_html(result['category'] if result['applied'] else 'none')}</code>)\n"
                f"📍 Destination: <i>{destination}</i>\n\n"
                f"Use /status to monitor download progress."
            )
            if result.get("warning"):
                body += f"\n\n⚠️ {escape_html(result['warning'])}"
            tgbot.send(token, chat_id, body)
        else:
            tgbot.send(
                token, chat_id,
                "❌ <b>Could not add this to qBittorrent.</b>\n\n"
                f"<code>{escape_html(result['error'] or 'qBittorrent rejected the torrent.')}</code>\n\n"
                "<i>Run /qbit for a connection diagnosis.</i>"
            )
        return

    # Smart YouTube / Web Video Link Handling (Interactive Menu)
    if video_handler.is_video_url(text) or "youtube.com" in text or "youtu.be" in text:
        link_id = str(uuid.uuid4())[:8]
        pending_media_links[link_id] = {"url": text, "timestamp": time.time()}

        is_pl = "list=" in text
        rows = [
            [
                {"text": "🎵 Audio (MP3 320k)", "callback_data": f"choice:mp3:{link_id}"},
                {"text": "🎧 Audio (FLAC)", "callback_data": f"choice:flac:{link_id}"},
            ],
            [
                {"text": "🎬 Movie / Video (Pick Quality)", "callback_data": f"choice:video:{link_id}"},
            ]
        ]
        if is_pl:
            rows.append([{"text": "📋 Full Playlist (MP3)", "callback_data": f"choice:playlist:{link_id}"}])
        rows.append([{"text": "❌ Cancel", "callback_data": f"choice:cancel:{link_id}"}])

        tgbot.send(
            token, chat_id,
            "🔗 <b>Media Link Detected</b>\nHow would you like to download this?",
            reply_markup=tgbot.inline_keyboard(rows),
        )
        return

    # Fallback message
    tgbot.send(
        token, chat_id,
        "❓ <i>Command or link not recognized.</i>\n\n"
        "• Send a <b>Magnet / .torrent link</b> to download torrent\n"
        "• Send a <b>YouTube link</b> for audio/video options\n"
        "• Use /help to see all available commands and features."
    )


def handle_media_upload(msg, cfg, token, chat_id):
    """Handle uploaded files: .torrent, video files, or audio tracks."""
    doc = msg.get("document")
    vid = msg.get("video")
    aud = msg.get("audio")

    # 1. Video Upload
    if vid:
        fname = vid.get("file_name", f"video_{int(time.time())}.mp4")
        video_handler.handle_uploaded_video(token, cfg, chat_id, vid["file_id"], fname)
        return

    # 2. Audio Upload
    if aud:
        fname = aud.get("file_name", f"audio_{int(time.time())}.mp3")
        music_handler.handle_uploaded_audio(token, cfg, chat_id, aud["file_id"], fname)
        return

    # 3. Document Upload
    if doc:
        fname = doc.get("file_name", "file")
        ext = os.path.splitext(fname)[1].lower()

        # Is it a .torrent file?
        if ext == ".torrent":
            tgbot.send_chat_action(token, chat_id, "typing")
            try:
                file_bytes, _ = tgbot.get_file_bytes(token, doc["file_id"])
            except Exception as e:
                tgbot.send(
                    token, chat_id,
                    f"❌ Could not download <code>{escape_html(fname)}</code> from Telegram:\n"
                    f"<code>{escape_html(str(e))}</code>"
                )
                return

            category, cat_label = torrent_handler.detect_category(fname)
            result = torrent_handler.add_torrent(cfg, file_bytes, category=category, filename=fname)
            if result["ok"]:
                destination = (
                    "category save path in qBittorrent" if result["applied"] else "qBittorrent default save path"
                )
                body = (
                    f"✅ <b>Torrent File Added to qBittorrent!</b>\n\n"
                    f"📄 File: <code>{escape_html(fname)}</code>\n"
                    f"📂 Category: <b>{cat_label}</b> "
                    f"(<code>{escape_html(result['category'] if result['applied'] else 'none')}</code>)\n"
                    f"📍 Destination: <i>{destination}</i>\n\n"
                    f"Use /status to track progress."
                )
                if result.get("warning"):
                    body += f"\n\n⚠️ {escape_html(result['warning'])}"
                tgbot.send(token, chat_id, body)
            else:
                tgbot.send(
                    token, chat_id,
                    "❌ <b>Failed to add the .torrent file.</b>\n\n"
                    f"<code>{escape_html(result['error'] or 'qBittorrent rejected the upload.')}</code>\n\n"
                    "<i>Run /qbit for a connection diagnosis.</i>"
                )
            return

        # Is it a video file?
        if ext in video_handler.VIDEO_EXTENSIONS:
            video_handler.handle_uploaded_video(token, cfg, chat_id, doc["file_id"], fname)
            return

        # Is it an audio file?
        if ext in music_handler.AUDIO_EXTENSIONS:
            music_handler.handle_uploaded_audio(token, cfg, chat_id, doc["file_id"], fname)
            return

        tgbot.send(
            token, chat_id,
            f"⚠️ Unsupported document type: <b>{escape_html(ext)}</b>\n\n"
            f"Supported:\n"
            f"• <b>.torrent</b> files -> qBittorrent\n"
            f"• <b>Video</b> (.mkv, .mp4, .avi, .mov, etc.) -> Movies\n"
            f"• <b>Audio</b> (.mp3, .flac, .m4a, .wav, etc.) -> Music"
        )


def set_torrents_running(token, chat_id, cfg, start):
    """Start/stop every torrent and report what qBittorrent actually answered."""
    verb = "resumed" if start else "paused"
    emoji = "▶️" if start else "⏸️"
    try:
        ok = torrent_handler.set_torrent_state(cfg, start=start, hashes="all")
    except Exception as e:
        return False, f"❌ Error talking to qBittorrent:\n<code>{escape_html(error_text(e))}</code>"

    if ok:
        return True, f"{emoji} <b>All torrents have been {verb} in qBittorrent.</b>"
    return False, (
        f"⚠️ qBittorrent did not apply the change. Nothing matched the request, or this "
        f"qBittorrent build does not expose the torrents/{'start' if start else 'stop'} endpoint."
    )


def report_qbit_connection(token, chat_id, cfg):
    """Diagnose the qBittorrent connection from inside Telegram (/qbit)."""
    report = torrent_handler.diagnose_connection(cfg)
    if report["ok"]:
        text = (
            "✅ <b>qBittorrent connection OK</b>\n\n"
            f"🔗 <code>{escape_html(report['base_url'])}</code>\n"
            f"📦 Version: <b>{escape_html(report['version'])}</b> "
            f"(Web API {escape_html(report['api_version'])})"
        )
        if report.get("auth_bypassed"):
            text += "\n🔓 Authentication is bypassed for this client."
    else:
        text = (
            "❌ <b>qBittorrent connection failed</b>\n\n"
            f"<code>{escape_html(report['message'])}</code>"
        )
        if report.get("hint"):
            text += f"\n\n💡 {escape_html(report['hint'])}"
        if report.get("base_url"):
            text += f"\n\n🔗 Tried: <code>{escape_html(report['base_url'])}</code>"
        text += "\n\n<i>Fix it in the web panel (port 8090) under qBittorrent Integration.</i>"
    tgbot.send(token, chat_id, text)
    return report


def process_update(update, cfg, token):
    """Main update dispatcher."""
    is_auth, user_id, chat_id = check_auth(update, cfg)
    if not is_auth:
        # Never answer strangers: it lets random people probe the bot and burns
        # Telegram API calls.  The ID is logged instead so the owner can copy it
        # straight into "Allowed Telegram User ID" in the web panel.
        print(
            f"[OpusBot] Ignored unauthorized request from user_id={user_id} chat_id={chat_id}. "
            f"If that is you, add this ID to allowed_user_id in the web panel."
        )
        return

    if "callback_query" in update:
        handle_callback(update, cfg, token)
    elif "message" in update:
        handle_message(update, cfg, token)


def main():
    """Bot entrypoint."""
    print("Starting OpusBots Unified Bot...")
    tgbot.run_polling(
        get_token=get_bot_token,
        process_fn=process_update,
        bot_name="OpusBot",
    )


if __name__ == "__main__":
    main()
