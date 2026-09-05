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
from shared.config import get_allowed_user_id, get_bot_token, load_config
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
            "• /pause - Pause all torrents in qBittorrent\n"
            "• /resume - Resume all torrents in qBittorrent\n\n"
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

    if data == "status:pause_all":
        try:
            torrent_handler.pause_torrents(cfg, hashes="all")
            tgbot.answer_callback(token, cb_id, "All torrents paused.", show_alert=False)
        except Exception as e:
            tgbot.answer_callback(token, cb_id, f"Error: {e}", show_alert=True)
        status_text = status_handler.build_status_text(cfg)
        tgbot.edit_message(token, chat_id, msg_id, status_text, reply_markup=status_handler.build_status_keyboard())
        return

    if data == "status:resume_all":
        try:
            torrent_handler.resume_torrents(cfg, hashes="all")
            tgbot.answer_callback(token, cb_id, "All torrents resumed.", show_alert=False)
        except Exception as e:
            tgbot.answer_callback(token, cb_id, f"Error: {e}", show_alert=True)
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

    if text in ["/pause", "/pause_all"]:
        try:
            torrent_handler.pause_torrents(cfg, hashes="all")
            tgbot.send(token, chat_id, "⏸️ <b>All torrents have been paused in qBittorrent.</b>")
        except Exception as e:
            tgbot.send(token, chat_id, f"❌ Error pausing torrents: <code>{escape_html(str(e))}</code>")
        return

    if text in ["/resume", "/resume_all"]:
        try:
            torrent_handler.resume_torrents(cfg, hashes="all")
            tgbot.send(token, chat_id, "▶️ <b>All torrents have been resumed in qBittorrent.</b>")
        except Exception as e:
            tgbot.send(token, chat_id, f"❌ Error resuming torrents: <code>{escape_html(str(e))}</code>")
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
    if text.startswith("/video "):
        url = text[7:].strip()
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
    if text.startswith("/yt ") or text.startswith("/mp3 "):
        url = text.split(maxsplit=1)[1].strip()
        music_handler.enqueue_job(
            token, chat_id,
            lambda u=url, c=chat_id: music_handler.download_song(token, cfg, c, u, quality="mp3"),
            label="MP3 Song Download"
        )
        return

    if text.startswith("/flac "):
        url = text[6:].strip()
        music_handler.enqueue_job(
            token, chat_id,
            lambda u=url, c=chat_id: music_handler.download_song(token, cfg, c, u, quality="flac"),
            label="FLAC Song Download"
        )
        return

    if text.startswith("/playlist "):
        url = text[10:].strip()
        music_handler.enqueue_job(
            token, chat_id,
            lambda u=url, c=chat_id: music_handler.download_playlist(token, cfg, c, u, quality="mp3"),
            label="Playlist Download"
        )
        return

    if text.startswith("/search "):
        query = text[8:].strip()
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
        try:
            success = torrent_handler.add_magnet(cfg, text, category=category)
            if success:
                tgbot.send(
                    token, chat_id,
                    f"✅ <b>Added to qBittorrent!</b>\n\n"
                    f"📂 Category: <b>{cat_label}</b> (<code>{category}</code>)\n"
                    f"📍 Destination: <code>{escape_html(cfg['paths']['downloads_completed'])}</code>\n\n"
                    f"Use /status to monitor download progress."
                )
            else:
                tgbot.send(token, chat_id, "❌ Failed to add to qBittorrent. Please check if qBittorrent is running.")
        except Exception as e:
            tgbot.send(token, chat_id, f"❌ qBittorrent Error:\n<code>{escape_html(str(e))}</code>")
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
                category, cat_label = torrent_handler.detect_category(fname)
                success = torrent_handler.add_torrent_file(cfg, file_bytes, fname, category=category)
                if success:
                    tgbot.send(
                        token, chat_id,
                        f"✅ <b>Torrent File Added to qBittorrent!</b>\n\n"
                        f"📄 File: <code>{escape_html(fname)}</code>\n"
                        f"📂 Category: <b>{cat_label}</b> (<code>{category}</code>)\n"
                        f"📍 Save path: <code>{escape_html(cfg['paths']['downloads_completed'])}</code>\n\n"
                        f"Use /status to track progress."
                    )
                else:
                    tgbot.send(token, chat_id, "❌ Failed to add .torrent file to qBittorrent.")
            except Exception as e:
                tgbot.send(token, chat_id, f"❌ Error uploading torrent:\n<code>{escape_html(str(e))}</code>")
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


def process_update(update, cfg, token):
    """Main update dispatcher."""
    is_auth, user_id, chat_id = check_auth(update, cfg)
    if not is_auth:
        tgbot.send(token, chat_id, "⛔ <b>Unauthorized.</b> Your user ID is not authorized to use this bot.")
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
