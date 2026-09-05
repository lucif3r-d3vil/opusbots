"""
Video and Movie download handler for OpusBots.
Handles YouTube and online video downloads (with resolution selector),
as well as direct Telegram video / document uploads to the Movies library.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time

from shared import tgbot
from shared.utils import escape_html, format_size, sanitize_filename

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v', '.ts', '.flv', '.webm'}

YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|embed/)|youtu\.be/)'
    r'[A-Za-z0-9_\-]{11}'
)

GENERIC_VIDEO_URL_REGEX = re.compile(
    r'https?://[^\s<>"]+\.(mp4|mkv|avi|mov|webm|ts|m4v)(\?[^\s<>"]*)?',
    re.IGNORECASE
)

# In-memory tracking
active_video_downloads = {}  # {download_id: {"title": ..., "chat_id": ..., "started": ..., "res": ...}}
pending_video_requests = {}  # {query_id: {"url": ..., "title": ..., "title_safe": ..., "formats": ...}}
video_history = []
HISTORY_MAX = 20
_video_lock = threading.Lock()


def is_youtube_url(text):
    """Check if text contains a YouTube video URL."""
    return bool(YOUTUBE_REGEX.search(text.strip()))


def is_video_url(text):
    """Check if text is any supported video link."""
    clean = text.strip()
    return is_youtube_url(clean) or bool(GENERIC_VIDEO_URL_REGEX.search(clean))


def get_video_formats(url):
    """
    Fetch available video formats from URL using yt-dlp.
    Returns (title, title_safe, sorted_formats, duration_str).
    """
    cmd = ["yt-dlp", "--dump-json", "--no-playlist", url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Failed to fetch video formats with yt-dlp"
        raise RuntimeError(error_msg)

    info = json.loads(result.stdout)
    title = info.get("title", "Video")
    title_safe = sanitize_filename(title, max_len=75, default="video")
    duration = info.get("duration_string", "")

    formats = info.get("formats", [])
    seen_res = {}
    ext_priority = {"mp4": 0, "mkv": 1, "webm": 2}

    for f in formats:
        vcodec = f.get("vcodec", "none")
        height = f.get("height")
        ext = f.get("ext", "mp4")
        fmt_id = f.get("format_id", "")
        filesize = f.get("filesize") or f.get("filesize_approx") or 0

        if not height or vcodec == "none" or "storyboard" in fmt_id.lower():
            continue

        res_label = f"{height}p"
        size_str = format_size(filesize) if filesize else "~"

        existing = seen_res.get(res_label)
        if existing is None or ext_priority.get(ext, 9) < ext_priority.get(existing["ext"], 9):
            seen_res[res_label] = {
                "id": fmt_id,
                "res": res_label,
                "ext": ext,
                "note": f.get("format_note", ""),
                "size": size_str,
                "height": height,
            }

    sorted_fmts = sorted(seen_res.values(), key=lambda x: -x["height"])
    return title, title_safe, sorted_fmts, duration


def build_resolution_keyboard(formats, query_id):
    """Build inline keyboard buttons for resolution selection."""
    rows = []
    row = []
    for i, fmt in enumerate(formats):
        label = f"🎬 {fmt['res']} ({fmt['size']})"
        row.append({"text": label, "callback_data": f"vres:{query_id}:{i}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "❌ Cancel", "callback_data": f"vcancel:{query_id}"}])
    return tgbot.inline_keyboard(rows)


def download_video_task(token, cfg, url, fmt_id, res_label, title_safe, chat_id, msg_id=None):
    """Execute video download and move to Movies directory."""
    download_id = f"{chat_id}_{int(time.time())}"
    dest_folder = cfg["paths"]["movies"]
    os.makedirs(dest_folder, exist_ok=True)

    with _video_lock:
        active_video_downloads[download_id] = {
            "title": title_safe,
            "res": res_label,
            "started": time.time(),
            "chat_id": chat_id,
        }

    status_text = (
        f"🎬 Downloading <b>{escape_html(title_safe)}</b>\n"
        f"Quality: <b>{res_label}</b>\n"
        f"<i>Saving to Movies library... Please wait.</i>"
    )
    if msg_id:
        tgbot.edit_message(token, chat_id, msg_id, status_text)
    else:
        msg_id = tgbot.send(token, chat_id, status_text)

    temp_template = f"/tmp/ytdl_vid_{download_id}.%(ext)s"
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", f"{fmt_id}+bestaudio/best[height<={fmt_id}]/best",
        "--merge-output-format", "mp4",
        "-o", temp_template,
        url,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            err = proc.stderr[-400:] if proc.stderr else "Download failed"
            raise RuntimeError(err)

        # Locate output file in /tmp
        expected_file = None
        for fn in os.listdir("/tmp"):
            if fn.startswith(f"ytdl_vid_{download_id}"):
                expected_file = os.path.join("/tmp", fn)
                break

        if not expected_file or not os.path.exists(expected_file):
            raise FileNotFoundError("Target downloaded video file was not found in temp directory.")

        ext = os.path.splitext(expected_file)[1] or ".mp4"
        dest_filename = f"{title_safe}{ext}"
        dest_path = os.path.join(dest_folder, dest_filename)

        # Collision avoidance
        base_path, dot_ext = os.path.splitext(dest_path)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = f"{base_path}_{counter}{dot_ext}"
            counter += 1

        shutil.move(expected_file, dest_path)
        size_bytes = os.path.getsize(dest_path)
        size_str = format_size(size_bytes)

        done_msg = (
            f"✅ <b>Movie Saved Successfully!</b>\n\n"
            f"📁 File: <code>{escape_html(os.path.basename(dest_path))}</code>\n"
            f"📊 Size: <b>{size_str}</b>\n"
            f"🎞️ Quality: <b>{res_label}</b>\n"
            f"📍 Location: <code>{escape_html(dest_folder)}</code>"
        )
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, done_msg)
        else:
            tgbot.send(token, chat_id, done_msg)

        with _video_lock:
            video_history.append({
                "title": title_safe,
                "size": size_str,
                "status": "completed",
                "ts": time.time(),
            })
            if len(video_history) > HISTORY_MAX:
                video_history.pop(0)

    except subprocess.TimeoutExpired:
        fail_msg = f"⏱️ Download timed out (>15 min) for <b>{escape_html(title_safe)}</b>. Try selecting a lower resolution."
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, fail_msg)
        else:
            tgbot.send(token, chat_id, fail_msg)
        with _video_lock:
            video_history.append({"title": title_safe, "size": "-", "status": "timeout", "ts": time.time()})
    except Exception as e:
        fail_msg = f"❌ Video download failed for <b>{escape_html(title_safe)}</b>:\n<code>{escape_html(str(e)[:300])}</code>"
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, fail_msg)
        else:
            tgbot.send(token, chat_id, fail_msg)
        with _video_lock:
            video_history.append({"title": title_safe, "size": "-", "status": "failed", "ts": time.time()})
    finally:
        with _video_lock:
            active_video_downloads.pop(download_id, None)
        # Clean up any leftover temp files
        for fn in os.listdir("/tmp"):
            if fn.startswith(f"ytdl_vid_{download_id}"):
                try:
                    os.remove(os.path.join("/tmp", fn))
                except Exception:
                    pass


def start_video_download(token, cfg, url, fmt_id, res_label, title_safe, chat_id, msg_id=None):
    """Spawn background thread for video download."""
    t = threading.Thread(
        target=download_video_task,
        args=(token, cfg, url, fmt_id, res_label, title_safe, chat_id, msg_id),
        daemon=True,
    )
    t.start()


def handle_uploaded_video(token, cfg, chat_id, file_id, original_name):
    """Handle direct video / document upload from Telegram."""
    movies_path = cfg["paths"]["movies"]
    os.makedirs(movies_path, exist_ok=True)

    tgbot.send_chat_action(token, chat_id, "upload_document")
    status_msg_id = tgbot.send(
        token, chat_id,
        f"📥 Receiving video file <b>{escape_html(original_name)}</b>..."
    )

    try:
        local_path, saved_fname = tgbot.download_file(token, file_id, dest_dir="/tmp")
        clean_fname = sanitize_filename(original_name, default=saved_fname)
        dest_path = os.path.join(movies_path, clean_fname)

        base_path, dot_ext = os.path.splitext(dest_path)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = f"{base_path}_{counter}{dot_ext}"
            counter += 1

        shutil.move(local_path, dest_path)
        size_str = format_size(os.path.getsize(dest_path))

        tgbot.edit_message(
            token, chat_id, status_msg_id,
            f"✅ <b>Video Saved to Movies!</b>\n\n"
            f"📁 File: <code>{escape_html(os.path.basename(dest_path))}</code>\n"
            f"📊 Size: <b>{size_str}</b>\n"
            f"📍 Location: <code>{escape_html(movies_path)}</code>"
        )
    except Exception as e:
        tgbot.edit_message(
            token, chat_id, status_msg_id,
            f"❌ Failed to save video file:\n<code>{escape_html(str(e))}</code>"
        )


def get_active_downloads():
    """Return dictionary of active video downloads."""
    with _video_lock:
        return dict(active_video_downloads)


def get_video_history():
    """Return list of recent video downloads."""
    with _video_lock:
        return list(video_history)
