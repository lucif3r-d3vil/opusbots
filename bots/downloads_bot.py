"""
OpusBots Movies Bot (service name stays "downloads-bot" for compose compatibility)

Strictly for movies:
  - Upload a video file  -> saved straight to the movies path.
  - Paste a YouTube link  -> pick a resolution -> saved straight to the movies path.

No audio handling here at all -- that's the music bot's job (see music_bot.py).
No TV handling here -- TV arrives via torrents (mirror_bot.py) and is sorted
by Sonarr on the host, outside these bots.
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

YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)'
    r'[A-Za-z0-9_\-]{11}'
)

# State (per-process, not persisted -- fine since only one instance runs)
pending = {}          # {chat_id: (local_path, fname)}
yt_pending = {}        # {chat_id: {...}}
active_downloads = {}  # {chat_id: {...}}
download_history = []
HISTORY_MAX = 20


def get_ext(fname):
    return os.path.splitext(fname)[1].lower()


def is_youtube_url(text):
    return bool(YOUTUBE_REGEX.search(text.strip()))


def get_yt_formats(url):
    """Video formats only -- no audio-only entries (that's music-bot's job)."""
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
    rows.append([{"text": "Cancel", "callback_data": "yt_cancel"}])
    return rows


def download_youtube(token, cfg, url, fmt_id, title_safe, chat_id):
    dest_folder = cfg["paths"]["movies"]
    os.makedirs(dest_folder, exist_ok=True)
    out_template = f"/tmp/ytdl_{chat_id}_{title_safe}.%(ext)s"

    cmd = ["yt-dlp", "--no-playlist", "-f", f"{fmt_id}+bestaudio/best[height<={fmt_id}]",
           "--merge-output-format", "mp4",
           "-o", out_template.replace("%(ext)s", "mp4"), url]
    final_ext = "mp4"

    active_downloads[chat_id] = {
        "title": title_safe, "started": time.time(), "res": fmt_id,
    }

    tgbot.send(token, chat_id, f"Downloading <b>{title_safe}</b>...\nThis may take a few minutes.")

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
            f"Saved.\n"
            f"File: <b>{os.path.basename(dest_path)}</b>\n"
            f"Size: <b>{size_mb:.1f} MB</b>"
        )
        download_history.append({"title": title_safe, "size_mb": size_mb,
                                  "status": "ok", "ts": time.time()})
        if len(download_history) > HISTORY_MAX:
            download_history.pop(0)

    except subprocess.TimeoutExpired:
        tgbot.send(token, chat_id, "Download timed out (>10 min). Try a lower resolution.")
        download_history.append({"title": title_safe, "size_mb": 0,
                                  "status": "timeout", "ts": time.time()})
        if len(download_history) > HISTORY_MAX:
            download_history.pop(0)
    except Exception as e:
        tgbot.send(token, chat_id, f"Download failed:\n<code>{str(e)[:300]}</code>")
        download_history.append({"title": title_safe, "size_mb": 0,
                                  "status": "failed", "ts": time.time()})
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
        tgbot.edit_message(token, chat_id, msg_id, "Cancelled.")
        return

    if data.startswith("yt_res:") and chat_id in yt_pending:
        state = yt_pending.pop(chat_id, None)
        idx = int(data.split(":")[1])
        fmt = state["formats"][idx]

        tgbot.edit_message(token, chat_id, msg_id,
            f"<b>{state['title']}</b>\nResolution: <b>{fmt['res']}</b>\nSaving to Movies..."
        )

        t = threading.Thread(
            target=download_youtube,
            args=(token, cfg, state["url"], fmt["id"], state["title_safe"], chat_id),
            daemon=True,
        )
        t.start()
        return


def process_message(update, cfg, token):
    msg = update["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    allowed = cfg["telegram"]["allowed_user_id"]
    movies_path = cfg["paths"]["movies"]

    if not allowed or user_id != allowed:
        tgbot.send(token, chat_id, "Unauthorized.")
        return

    if "text" in msg and msg["text"].strip() == "/start":
        tgbot.send(token, chat_id,
            "<b>OpusBots Movies Bot</b>\n\n"
            "Upload a video file, or paste a YouTube link, and I'll save it\n"
            "to your movies library.\n\n"
            "Supported upload formats: mkv, mp4, avi, mov, wmv, m4v, ts, flv, webm\n\n"
            "/status - active downloads and recent history"
        )
        return

    if "text" in msg and msg["text"].strip() == "/status":
        lines = ["<b>Movies Bot Status</b>\n"]

        if active_downloads:
            lines.append("Active:")
            for cid, dl in active_downloads.items():
                elapsed = int(time.time() - dl["started"])
                mins, secs = divmod(elapsed, 60)
                lines.append(f"  {dl['title'][:40]} -- {dl['res']} -- {mins}m{secs:02d}s elapsed")
            lines.append("")
        else:
            lines.append("No active downloads\n")

        try:
            st = os.statvfs(movies_path)
            free_gb = st.f_bavail * st.f_frsize / 1024 ** 3
            total_gb = st.f_blocks * st.f_frsize / 1024 ** 3
            used_pct = 100 - (st.f_bavail / st.f_blocks * 100) if st.f_blocks else 0
            bar_filled = int(used_pct / 10)
            bar = "#" * bar_filled + "-" * (10 - bar_filled)
            lines.append(f"Movies disk: {free_gb:.1f} GB free / {total_gb:.1f} GB  [{bar}] {used_pct:.0f}% used")
        except Exception:
            lines.append("Movies disk: unavailable")
        lines.append("")

        if download_history:
            lines.append("Recent downloads:")
            import datetime
            for entry in reversed(download_history[-10:]):
                ts = datetime.datetime.fromtimestamp(entry["ts"]).strftime("%m/%d %H:%M")
                size = f"{entry['size_mb']:.1f}MB" if entry.get("size_mb") else ""
                lines.append(f"  [{entry['status']}] {entry['title'][:40]} {size} ({ts})")
        else:
            lines.append("No download history yet")

        tgbot.send(token, chat_id, "\n".join(lines))
        return

    if "text" in msg and is_youtube_url(msg["text"]):
        url = msg["text"].strip()
        tgbot.send(token, chat_id, "Fetching available resolutions...")
        try:
            title, title_safe, formats = get_yt_formats(url)
        except Exception as e:
            tgbot.send(token, chat_id, f"Could not fetch video info:\n<code>{str(e)[:300]}</code>")
            return

        if not formats:
            tgbot.send(token, chat_id, "No downloadable video formats found for this link.")
            return

        yt_pending[chat_id] = {
            "url": url, "title": title, "title_safe": title_safe, "formats": formats,
        }

        rows = build_resolution_keyboard(formats)
        tgbot.send(token, chat_id,
            f"<b>{title}</b>\n\nChoose a resolution:",
            reply_markup=tgbot.inline_keyboard(rows),
        )
        return

    file_id = fname = None

    if "video" in msg:
        file_id = msg["video"]["file_id"]
        fname = msg["video"].get("file_name", "video.mp4")
    elif "document" in msg:
        file_id = msg["document"]["file_id"]
        fname = msg["document"].get("file_name", "file")
        ext = get_ext(fname)
        if ext not in VIDEO_EXT:
            tgbot.send(token, chat_id,
                f"Unsupported format: <b>{ext}</b>\n\n"
                "This bot only handles movies (video files). For music, use the music bot instead.\n"
                "Supported: mkv, mp4, avi, mov, wmv, m4v, ts, flv, webm"
            )
            return
    elif "audio" in msg:
        tgbot.send(token, chat_id, "This bot only handles movies. Send audio to the music bot instead.")
        return
    elif "text" in msg:
        tgbot.send(token, chat_id, "Send a video file or a YouTube link. Use /start for details.")
        return

    if file_id:
        tgbot.send_chat_action(token, chat_id, "upload_document")
        tgbot.send(token, chat_id, f"Receiving <b>{fname}</b>...")
        try:
            local_path, saved_fname = tgbot.download_file(token, file_id)
            os.makedirs(movies_path, exist_ok=True)
            dest_path = os.path.join(movies_path, saved_fname)
            shutil.move(local_path, dest_path)
            tgbot.send(token, chat_id, f"Saved.\nFile: <b>{saved_fname}</b>")
        except Exception as e:
            tgbot.send(token, chat_id, f"Error saving file: {str(e)}")


def process_update(update, cfg, token):
    if "callback_query" in update:
        process_callback(update, cfg, token)
    elif "message" in update:
        process_message(update, cfg, token)


if __name__ == "__main__":
    tgbot.run_polling(
        get_token=lambda cfg: cfg["telegram"]["downloads_bot_token"],
        process_fn=process_update,
        bot_name="Movies Bot",
    )
