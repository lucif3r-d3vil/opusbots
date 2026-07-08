"""
HomeLab Downloads Bot
Upload a video/audio file -> pick a folder to save it to.
Send a YouTube link -> pick a resolution, then a folder.
/status shows active downloads, disk space, and recent history.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time

from shared import tgbot
from shared.config import load_config

VIDEO_EXT = ['.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v', '.ts', '.flv', '.webm']
AUDIO_EXT = ['.mp3', '.flac', '.m4a', '.ogg', '.wav', '.aac', '.opus', '.wma']

YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)'
    r'[A-Za-z0-9_\-]{11}'
)

# ── State (per-process, not persisted — fine since only one instance runs) ──
pending = {}          # {chat_id: (local_path, fname, file_type)}
yt_pending = {}        # {chat_id: {...}}
active_downloads = {}  # {chat_id: {...}}
download_history = []
HISTORY_MAX = 20


def folder_map(cfg):
    p = cfg["paths"]
    return {
        "movies": p["movies"],
        "movie": p["movies"],
        "tv": p["tv"],
        "shows": p["tv"],
        "music": p["music"],
        "songs": p["music"],
        "audio": p["music"],
    }


def get_ext(fname):
    return os.path.splitext(fname)[1].lower()


def is_youtube_url(text):
    return bool(YOUTUBE_REGEX.search(text.strip()))


def get_yt_formats(url):
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-playlist", url],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yt-dlp failed")

    info = json.loads(result.stdout)
    title = info.get("title", "video")
    title_safe = re.sub(r'[^\w\s\-\.]', '', title).strip()[:80] or "video"

    formats = info.get("formats", [])
    seen_res = {}
    ext_prio = {"mp4": 0, "webm": 1, "mkv": 2}

    for f in formats:
        vcodec = f.get("vcodec", "none")
        height = f.get("height")
        ext = f.get("ext", "mp4")
        fmt_id = f.get("format_id", "")
        filesize = f.get("filesize") or f.get("filesize_approx") or 0

        if not height or vcodec == "none" or "storyboard" in fmt_id.lower():
            continue

        res_label = f"{height}p"
        size_str = f"{filesize/1024/1024:.0f}MB" if filesize else "~"

        existing = seen_res.get(res_label)
        if existing is None or ext_prio.get(ext, 9) < ext_prio.get(existing["ext"], 9):
            seen_res[res_label] = {
                "id": fmt_id, "res": res_label, "ext": ext,
                "note": f.get("format_note", ""), "size": size_str, "height": height,
            }

    best_audio = None
    for f in formats:
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            ext = f.get("ext", "m4a")
            if ext in ("m4a", "mp3", "opus"):
                filesize = f.get("filesize") or f.get("filesize_approx") or 0
                if best_audio is None or filesize > best_audio.get("filesize", 0):
                    best_audio = {
                        "id": f.get("format_id"), "res": "audio", "ext": ext,
                        "note": "audio only",
                        "size": f"{filesize/1024/1024:.0f}MB" if filesize else "~",
                        "height": 0, "filesize": filesize,
                    }
    if best_audio:
        seen_res["audio"] = best_audio

    sorted_fmts = sorted(seen_res.values(), key=lambda x: -x["height"])
    return title, title_safe, sorted_fmts


def build_resolution_keyboard(formats):
    rows, row = [], []
    for i, fmt in enumerate(formats):
        label = f"{fmt['res']} ({fmt['ext']}) {fmt['size']}"
        row.append({"text": label, "callback_data": f"yt_res:{i}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "❌ Cancel", "callback_data": "yt_cancel"}])
    return rows


def build_folder_keyboard(file_type):
    keys = ["music", "movies", "tv"] if file_type == "audio" else ["movies", "tv", "music"]
    rows = [[{"text": k.capitalize(), "callback_data": f"folder:{k}"} for k in keys]]
    rows.append([{"text": "❌ Cancel", "callback_data": "yt_cancel"}])
    return rows


def download_youtube(token, url, fmt_id, ext, title_safe, dest_folder, chat_id):
    os.makedirs(dest_folder, exist_ok=True)
    out_template = f"/tmp/ytdl_{chat_id}_{title_safe}.%(ext)s"

    if fmt_id == "audio_only":
        cmd = ["yt-dlp", "--no-playlist", "-f", "bestaudio", "--extract-audio",
               "--audio-format", "mp3", "--audio-quality", "0",
               "-o", out_template.replace("%(ext)s", "mp3"), url]
        final_ext = "mp3"
    else:
        cmd = ["yt-dlp", "--no-playlist", "-f", f"{fmt_id}+bestaudio/best[height<={fmt_id}]",
               "--merge-output-format", "mp4",
               "-o", out_template.replace("%(ext)s", "mp4"), url]
        final_ext = "mp4"

    res_label = "audio" if fmt_id == "audio_only" else fmt_id
    active_downloads[chat_id] = {
        "title": title_safe, "started": time.time(), "folder": dest_folder, "res": res_label,
    }

    tgbot.send(token, chat_id, f"⏳ Downloading <b>{title_safe}</b>…\nThis may take a few minutes.")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-400:] if proc.stderr else "Download failed")

        expected = out_template.replace("%(ext)s", final_ext)
        if not os.path.exists(expected):
            for fn in os.listdir("/tmp"):
                if fn.startswith(f"ytdl_{chat_id}_"):
                    expected = f"/tmp/{fn}"
                    final_ext = fn.rsplit(".", 1)[-1]
                    break

        if not os.path.exists(expected):
            raise FileNotFoundError("Downloaded file not found")

        dest_name = f"{title_safe}.{final_ext}"
        dest_path = os.path.join(dest_folder, dest_name)
        base, dot_ext = os.path.splitext(dest_path)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = f"{base}_{counter}{dot_ext}"
            counter += 1

        shutil.move(expected, dest_path)
        size_mb = os.path.getsize(dest_path) / 1024 / 1024

        tgbot.send(token, chat_id,
            f"✅ <b>Saved!</b>\n"
            f"📄 <b>{os.path.basename(dest_path)}</b>\n"
            f"📁 Folder: <b>{dest_folder}</b>\n"
            f"💾 Size: <b>{size_mb:.1f} MB</b>"
        )
        download_history.append({"title": title_safe, "folder": dest_folder, "res": res_label,
                                  "size_mb": size_mb, "status": "✅", "ts": time.time()})
        if len(download_history) > HISTORY_MAX:
            download_history.pop(0)

    except subprocess.TimeoutExpired:
        tgbot.send(token, chat_id, "❌ Download timed out (>10 min). Try a lower resolution.")
        download_history.append({"title": title_safe, "folder": dest_folder, "res": res_label,
                                  "size_mb": 0, "status": "❌ timeout", "ts": time.time()})
        if len(download_history) > HISTORY_MAX:
            download_history.pop(0)
    except Exception as e:
        tgbot.send(token, chat_id, f"❌ Download failed:\n<code>{str(e)[:300]}</code>")
        download_history.append({"title": title_safe, "folder": dest_folder, "res": res_label,
                                  "size_mb": 0, "status": "❌ failed", "ts": time.time()})
        if len(download_history) > HISTORY_MAX:
            download_history.pop(0)
    finally:
        active_downloads.pop(chat_id, None)
        for fn in os.listdir("/tmp"):
            if fn.startswith(f"ytdl_{chat_id}_"):
                try:
                    os.remove(f"/tmp/{fn}")
                except Exception:
                    pass


def process_callback(update, cfg, token):
    cb = update["callback_query"]
    chat_id = cb["message"]["chat"]["id"]
    user_id = cb["from"]["id"]
    msg_id = cb["message"]["message_id"]
    data = cb.get("data", "")

    tgbot.answer_callback(token, cb["id"])

    if user_id != cfg["telegram"]["allowed_user_id"]:
        return

    if data == "yt_cancel":
        yt_pending.pop(chat_id, None)
        pending.pop(chat_id, None)
        tgbot.edit_message(token, chat_id, msg_id, "❌ Cancelled.")
        return

    if data.startswith("yt_res:") and chat_id in yt_pending:
        state = yt_pending[chat_id]
        idx = int(data.split(":")[1])
        fmt = state["formats"][idx]

        state["fmt_id"] = fmt["id"] if fmt["res"] != "audio" else "audio_only"
        state["ext"] = fmt["ext"]
        state["step"] = "folder"
        state["file_type"] = "audio" if fmt["res"] == "audio" else "video"

        file_type = state["file_type"]
        tgbot.edit_message(token, chat_id, msg_id,
            f"{'🎵' if file_type == 'audio' else '🎬'} <b>{state['title']}</b>\n"
            f"Resolution: <b>{fmt['res']}</b>\n\n"
            f"Which folder should I save it to?"
        )
        rows = build_folder_keyboard(file_type)
        tgbot.send(token, chat_id, "Choose a folder:", reply_markup=tgbot.inline_keyboard(rows))
        return

    if data.startswith("folder:") and chat_id in yt_pending:
        folder_key = data.split(":")[1]
        state = yt_pending.pop(chat_id, None)
        if not state:
            return

        dest_folder = folder_map(cfg).get(folder_key)
        if not dest_folder:
            tgbot.send(token, chat_id, "❌ Unknown folder.")
            return

        tgbot.edit_message(token, chat_id, msg_id, f"📁 Saving to <b>{dest_folder}</b>…")

        t = threading.Thread(
            target=download_youtube,
            args=(token, state["url"], state["fmt_id"], state["ext"],
                  state["title_safe"], dest_folder, chat_id),
            daemon=True,
        )
        t.start()
        return

    if data.startswith("folder:") and chat_id in pending:
        folder_key = data.split(":")[1]
        local_path, fname, file_type = pending.pop(chat_id)
        dest_folder = folder_map(cfg).get(folder_key)
        if not dest_folder:
            tgbot.send(token, chat_id, "❌ Unknown folder.")
            return
        try:
            os.makedirs(dest_folder, exist_ok=True)
            shutil.move(local_path, f"{dest_folder}/{fname}")
            tgbot.edit_message(token, chat_id, msg_id,
                f"✅ <b>Saved!</b>\n📄 <b>{fname}</b>\n📁 <b>{dest_folder}</b>"
            )
        except Exception as e:
            tgbot.send(token, chat_id, f"❌ Error: {str(e)}")
        return


def process_message(update, cfg, token):
    msg = update["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    allowed = cfg["telegram"]["allowed_user_id"]

    if not allowed or user_id != allowed:
        tgbot.send(token, chat_id, "⛔ Unauthorized.")
        return

    if "text" in msg and msg["text"].strip() == "/start":
        tgbot.send(token, chat_id,
            "📥 <b>HomeLab Downloads Bot</b>\n\n"
            "<b>Upload a file</b> — video or audio → I'll ask where to save it.\n\n"
            "<b>Send a YouTube link</b> — I'll show available resolutions.\n\n"
            "<b>Available folders:</b>\n"
            "• <b>movies</b> — Movies\n"
            "• <b>tv</b> — TV Shows\n"
            "• <b>music</b> — Music\n\n"
            "<b>Supported upload formats:</b>\n"
            "Video: mkv, mp4, avi, mov, wmv, m4v, ts\n"
            "Audio: mp3, flac, m4a, ogg, wav, aac, opus\n\n"
            "📊 /status — show active downloads & history"
        )
        return

    if "text" in msg and msg["text"].strip() == "/status":
        lines = ["📊 <b>Downloads Status</b>\n"]

        if active_downloads:
            lines.append("⏳ <b>Active:</b>")
            for cid, dl in active_downloads.items():
                elapsed = int(time.time() - dl["started"])
                mins, secs = divmod(elapsed, 60)
                lines.append(
                    f"  • <b>{dl['title'][:40]}</b>\n"
                    f"    {dl['res']} → {dl['folder'].split('/')[-1]} — {mins}m{secs:02d}s elapsed"
                )
            lines.append("")
        else:
            lines.append("✅ No active downloads\n")

        lines.append("💾 <b>Disk space:</b>")
        shown = set()
        for key, path in folder_map(cfg).items():
            if path in shown:
                continue
            shown.add(path)
            try:
                st = os.statvfs(path)
                free_gb = st.f_bavail * st.f_frsize / 1024 ** 3
                total_gb = st.f_blocks * st.f_frsize / 1024 ** 3
                used_pct = 100 - (st.f_bavail / st.f_blocks * 100)
                folder_name = path.split('/')[-1]
                bar_filled = int(used_pct / 10)
                bar = "█" * bar_filled + "░" * (10 - bar_filled)
                lines.append(
                    f"  <b>{folder_name}</b>: {free_gb:.1f} GB free / {total_gb:.1f} GB  "
                    f"[{bar}] {used_pct:.0f}%"
                )
            except Exception:
                lines.append(f"  <b>{path.split('/')[-1]}</b>: unavailable")
        lines.append("")

        if download_history:
            lines.append("📋 <b>Recent downloads:</b>")
            for entry in reversed(download_history[-10:]):
                import datetime
                ts = datetime.datetime.fromtimestamp(entry["ts"]).strftime("%m/%d %H:%M")
                size = f"{entry['size_mb']:.1f}MB" if entry.get("size_mb") else ""
                folder_name = entry.get("folder", "").split("/")[-1]
                lines.append(
                    f"  {entry['status']} <b>{entry['title'][:35]}</b>\n"
                    f"    {entry.get('res','file')} → {folder_name} {size} <i>{ts}</i>"
                )
        else:
            lines.append("📋 No download history yet")

        tgbot.send(token, chat_id, "\n".join(lines))
        return

    if "text" in msg and is_youtube_url(msg["text"]):
        url = msg["text"].strip()
        tgbot.send(token, chat_id, "🔍 Fetching available resolutions…")
        try:
            title, title_safe, formats = get_yt_formats(url)
        except Exception as e:
            tgbot.send(token, chat_id, f"❌ Could not fetch video info:\n<code>{str(e)[:300]}</code>")
            return

        if not formats:
            tgbot.send(token, chat_id, "❌ No downloadable formats found for this video.")
            return

        yt_pending[chat_id] = {
            "url": url, "title": title, "title_safe": title_safe,
            "formats": formats, "step": "res",
        }

        rows = build_resolution_keyboard(formats)
        tgbot.send(token, chat_id,
            f"🎬 <b>{title}</b>\n\nChoose a resolution to download:",
            reply_markup=tgbot.inline_keyboard(rows),
        )
        return

    file_id = fname = file_type = None

    if "video" in msg:
        file_id = msg["video"]["file_id"]
        fname = msg["video"].get("file_name", "video.mp4")
        file_type = "video"
    elif "audio" in msg:
        file_id = msg["audio"]["file_id"]
        fname = msg["audio"].get("file_name", "audio.mp3")
        file_type = "audio"
    elif "document" in msg:
        file_id = msg["document"]["file_id"]
        fname = msg["document"].get("file_name", "file")
        ext = get_ext(fname)
        if ext in VIDEO_EXT:
            file_type = "video"
        elif ext in AUDIO_EXT:
            file_type = "audio"
        else:
            tgbot.send(token, chat_id,
                f"⚠️ Unsupported format: <b>{ext}</b>\n\n"
                "Supported:\nVideo: mkv, mp4, avi, mov, wmv, m4v\n"
                "Audio: mp3, flac, m4a, ogg, wav, aac"
            )
            return
    elif "text" in msg:
        tgbot.send(token, chat_id,
            "⚠️ Please send a video/audio file or a YouTube link.\nUse /start to see instructions."
        )
        return

    if file_id:
        tgbot.send_chat_action(token, chat_id, "upload_document")
        tgbot.send(token, chat_id, f"📥 Receiving <b>{fname}</b>…")
        try:
            local_path, saved_fname = tgbot.download_file(token, file_id)
            pending[chat_id] = (local_path, saved_fname, file_type)
            emoji = "🎬" if file_type == "video" else "🎵"
            tgbot.send(token, chat_id,
                f"{emoji} <b>{'Video' if file_type == 'video' else 'Audio'} received!</b>\n"
                f"📄 <b>{saved_fname}</b>\n\nWhich folder should I save it to?",
                reply_markup=tgbot.inline_keyboard(build_folder_keyboard(file_type)),
            )
        except Exception as e:
            tgbot.send(token, chat_id, f"❌ Error receiving file: {str(e)}")


def process_update(update, cfg, token):
    if "callback_query" in update:
        process_callback(update, cfg, token)
    elif "message" in update:
        process_message(update, cfg, token)


if __name__ == "__main__":
    tgbot.run_polling(
        get_token=lambda cfg: cfg["telegram"]["downloads_bot_token"],
        process_fn=process_update,
        bot_name="Downloads Bot",
    )
