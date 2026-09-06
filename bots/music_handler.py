"""
Music download handler for OpusBots.
Handles MP3 / FLAC single song downloads, full playlist downloads,
YouTube audio searches, and background download queue processing.
"""

import os
import queue
import re
import shutil
import subprocess
import threading
import time

from shared import tgbot
from shared.utils import escape_html, format_size, progress_bar, sanitize_filename

AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac', '.alac'}

job_queue = queue.Queue()
_music_lock = threading.Lock()
current_job_info = {}
is_downloading = False


def _queue_worker():
    """Background worker thread processing audio download jobs sequentially."""
    global is_downloading
    while True:
        job = job_queue.get()
        is_downloading = True
        try:
            job()
        except Exception as e:
            print(f"[MusicHandler] Job error: {e}")
        finally:
            with _music_lock:
                current_job_info.clear()
            is_downloading = False
            job_queue.task_done()


# Start the background worker daemon immediately
threading.Thread(target=_queue_worker, daemon=True, name="MusicQueueWorker").start()


def parse_progress(line):
    """Parse yt-dlp download progress line."""
    match = re.search(
        r'\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+\S*)\s+at\s+([\d.]+\S+/s)\s+ETA\s+(\S+)',
        line,
    )
    if match:
        return {
            "percent": float(match.group(1)),
            "size": match.group(2),
            "speed": match.group(3),
            "eta": match.group(4),
        }
    return None


def _run_ytdlp_audio_stream(token, chat_id, cmd, title, artist, duration, quality, msg_id):
    """Run yt-dlp subprocess while streaming progress back to Telegram."""
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    last_edit = 0
    percent = 0.0
    speed = ""
    eta = ""
    size = ""

    with _music_lock:
        current_job_info.update({
            "title": title,
            "artist": artist,
            "quality": quality.upper(),
            "percent": 0.0,
        })

    for line in iter(process.stdout.readline, ""):
        line = line.strip()
        p = parse_progress(line)
        if p:
            percent = p["percent"]
            speed = p["speed"]
            eta = p["eta"]
            size = p["size"]
            with _music_lock:
                current_job_info.update({
                    "percent": percent,
                    "speed": speed,
                    "eta": eta,
                    "size": size,
                })

        now = time.time()
        if msg_id and (now - last_edit > 2.2):
            bar = progress_bar(percent, width=10)
            spd_text = speed if speed else "Processing audio..."
            eta_text = f" • ETA: {eta}" if eta else ""
            size_text = f" • {size}" if size else ""

            text = (
                f"🎵 <b>{escape_html(title)}</b>\n"
                f"👤 {escape_html(artist)} | ⏱️ {escape_html(duration)} | 🏷️ {quality.upper()}\n\n"
                f"[{bar}] {percent:.1f}%\n"
                f"⚡ {spd_text}{size_text}{eta_text}"
            )
            tgbot.edit_message(token, chat_id, msg_id, text)
            last_edit = now

    process.wait()
    return process.returncode


def download_song(token, cfg, chat_id, url, quality="mp3"):
    """Download single audio track with embedded tags and thumbnail."""
    music_path = cfg["paths"]["music"]
    os.makedirs(music_path, exist_ok=True)
    msg_id = tgbot.send(token, chat_id, "🔍 Fetching song metadata...")

    try:
        info_cmd = [
            "yt-dlp",
            "--print", "%(title)s|||%(uploader,artist)s|||%(duration_string)s",
            "--no-playlist",
            url,
        ]
        info_proc = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)

        title, artist, duration = "Unknown Track", "Unknown Artist", "?"
        if info_proc.returncode == 0 and "|||" in info_proc.stdout:
            parts = info_proc.stdout.strip().split("|||")
            if len(parts) >= 1 and parts[0].strip():
                title = parts[0].strip()
            if len(parts) >= 2 and parts[1].strip():
                artist = parts[1].strip()
            if len(parts) >= 3 and parts[2].strip():
                duration = parts[2].strip()

        audio_format = "flac" if quality.lower() == "flac" else "mp3"
        output_template = os.path.join(
            music_path,
            "%(uploader,artist)s",
            "%(album,uploader,artist)s",
            "%(title)s.%(ext)s"
        )

        cmd = [
            "yt-dlp",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", audio_format,
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--embed-metadata",
            "--add-metadata",
            "--newline",
            "-o", output_template,
            url,
        ]

        rc = _run_ytdlp_audio_stream(token, chat_id, cmd, title, artist, duration, audio_format, msg_id)

        if rc == 0:
            if msg_id:
                tgbot.edit_message(
                    token, chat_id, msg_id,
                    f"✅ <b>Music Saved to Library!</b>\n\n"
                    f"🎵 Title: <b>{escape_html(title)}</b>\n"
                    f"👤 Artist: <b>{escape_html(artist)}</b>\n"
                    f"🎧 Format: <b>{audio_format.upper()}</b>\n"
                    f"📍 Path: <code>{escape_html(music_path)}</code>"
                )
        else:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, f"❌ Download failed for: <b>{escape_html(title)}</b>")

    except Exception as e:
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, f"❌ Error downloading song: <code>{escape_html(str(e))}</code>")


def download_playlist(token, cfg, chat_id, url, quality="mp3"):
    """Download full YouTube playlist with overall progress and track progress."""
    music_path = cfg["paths"]["music"]
    os.makedirs(music_path, exist_ok=True)
    msg_id = tgbot.send(token, chat_id, "🔍 Fetching playlist details...")

    try:
        info_cmd = [
            "yt-dlp",
            "--print", "%(playlist_title)s|||%(playlist_count)s",
            "--playlist-items", "1",
            url,
        ]
        info_proc = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)

        playlist_title, total_count = "Playlist", 0
        if info_proc.returncode == 0 and "|||" in info_proc.stdout:
            parts = info_proc.stdout.strip().split("|||")
            if len(parts) >= 1 and parts[0].strip():
                playlist_title = parts[0].strip()
            if len(parts) >= 2:
                try:
                    total_count = int(parts[1].strip())
                except Exception:
                    total_count = 0

        audio_format = "flac" if quality.lower() == "flac" else "mp3"
        output_template = os.path.join(
            music_path,
            "%(uploader,artist)s",
            "%(playlist_title)s",
            "%(playlist_index)02d - %(title)s.%(ext)s"
        )

        cmd = [
            "yt-dlp",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", audio_format,
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--embed-metadata",
            "--add-metadata",
            "--newline",
            "-o", output_template,
            url,
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        last_edit = 0
        current_song = "Starting..."
        current_index = 0
        song_percent = 0.0
        speed = ""
        eta = ""

        for line in iter(process.stdout.readline, ""):
            line = line.strip()

            idx_match = re.search(r'\[download\] Downloading item (\d+) of (\d+)', line)
            if idx_match:
                current_index = int(idx_match.group(1))
                if total_count == 0:
                    total_count = int(idx_match.group(2))
                song_percent = 0.0

            dest_match = re.search(r'\[download\] Destination:.+?(\d+)\s+-\s+(.+?)\.(mp3|flac|m4a|webm|opus)', line)
            if dest_match:
                current_song = dest_match.group(2)[:35]

            p = parse_progress(line)
            if p:
                song_percent = p["percent"]
                speed = p["speed"]
                eta = p["eta"]

            now = time.time()
            if msg_id and (now - last_edit > 2.5):
                overall_pct = (current_index / total_count * 100.0) if total_count > 0 else 0.0
                overall_bar = progress_bar(overall_pct, width=10)
                song_bar = progress_bar(song_percent, width=8)
                spd_text = speed if speed else "Processing..."
                eta_text = f" • ETA: {eta}" if eta else ""

                text = (
                    f"📋 <b>{escape_html(playlist_title)}</b>\n\n"
                    f"Overall: [{overall_bar}] {overall_pct:.1f}%\n"
                    f"Track: <b>{current_index}</b> of <b>{total_count}</b>\n\n"
                    f"Now: <i>{escape_html(current_song)}</i>\n"
                    f"[{song_bar}] {song_percent:.1f}%\n"
                    f"⚡ {spd_text}{eta_text}"
                )
                tgbot.edit_message(token, chat_id, msg_id, text)
                last_edit = now

        process.wait()

        if process.returncode == 0:
            if msg_id:
                tgbot.edit_message(
                    token, chat_id, msg_id,
                    f"✅ <b>Playlist Complete!</b>\n\n"
                    f"📋 <b>{escape_html(playlist_title)}</b>\n"
                    f"📊 All <b>{total_count}</b> tracks saved.\n"
                    f"📍 Location: <code>{escape_html(music_path)}</code>"
                )
        else:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, "⚠️ Playlist download finished with warnings. Some tracks may have failed.")

    except Exception as e:
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, f"❌ Playlist error: <code>{escape_html(str(e))}</code>")


def search_and_download(token, cfg, chat_id, query, quality="mp3"):
    """Search YouTube for query and download best match."""
    msg_id = tgbot.send(token, chat_id, f"🔍 Searching YouTube for: <b>{escape_html(query)}</b>...")

    try:
        info_cmd = [
            "yt-dlp",
            "--print", "%(title)s|||%(uploader,artist)s|||%(duration_string)s|||%(webpage_url)s",
            "--no-playlist",
            f"ytsearch1:{query} audio",
        ]
        info_proc = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)

        if info_proc.returncode != 0 or "|||" not in info_proc.stdout:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, f"❌ No results found for: <b>{escape_html(query)}</b>")
            return

        parts = info_proc.stdout.strip().split("|||")
        title = parts[0].strip() if len(parts) > 0 else query
        artist = parts[1].strip() if len(parts) > 1 else "Unknown"
        duration = parts[2].strip() if len(parts) > 2 else "?"
        found_url = parts[3].strip() if len(parts) > 3 else ""

        if not found_url:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, f"❌ Could not find video URL for: <b>{escape_html(query)}</b>")
            return

        audio_format = "flac" if quality.lower() == "flac" else "mp3"
        music_path = cfg["paths"]["music"]
        os.makedirs(music_path, exist_ok=True)
        output_template = os.path.join(
            music_path,
            "%(uploader,artist)s",
            "%(album,uploader,artist)s",
            "%(title)s.%(ext)s"
        )

        cmd = [
            "yt-dlp",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", audio_format,
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--embed-metadata",
            "--add-metadata",
            "--newline",
            "-o", output_template,
            found_url,
        ]

        rc = _run_ytdlp_audio_stream(token, chat_id, cmd, title, artist, duration, audio_format, msg_id)

        if rc == 0:
            if msg_id:
                tgbot.edit_message(
                    token, chat_id, msg_id,
                    f"✅ <b>Music Saved to Library!</b>\n\n"
                    f"🎵 Title: <b>{escape_html(title)}</b>\n"
                    f"👤 Artist: <b>{escape_html(artist)}</b>\n"
                    f"🎧 Format: <b>{audio_format.upper()}</b>\n"
                    f"📍 Path: <code>{escape_html(music_path)}</code>"
                )
        else:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, f"❌ Download failed for: <b>{escape_html(title)}</b>")

    except Exception as e:
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, f"❌ Search error: <code>{escape_html(str(e))}</code>")


def handle_uploaded_audio(token, cfg, chat_id, file_id, original_name):
    """Handle direct audio file upload from Telegram."""
    music_path = cfg["paths"]["music"]
    os.makedirs(music_path, exist_ok=True)

    tgbot.send_chat_action(token, chat_id, "upload_document")
    status_msg_id = tgbot.send(
        token, chat_id,
        f"📥 Receiving audio file <b>{escape_html(original_name)}</b>..."
    )

    try:
        local_path, saved_fname = tgbot.download_file(token, file_id, dest_dir="/tmp")
        clean_fname = sanitize_filename(original_name, default=saved_fname)
        dest_path = os.path.join(music_path, clean_fname)

        base_path, dot_ext = os.path.splitext(dest_path)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = f"{base_path}_{counter}{dot_ext}"
            counter += 1

        shutil.move(local_path, dest_path)
        size_str = format_size(os.path.getsize(dest_path))

        tgbot.edit_message(
            token, chat_id, status_msg_id,
            f"✅ <b>Audio Saved to Music!</b>\n\n"
            f"🎵 File: <code>{escape_html(os.path.basename(dest_path))}</code>\n"
            f"📊 Size: <b>{size_str}</b>\n"
            f"📍 Location: <code>{escape_html(music_path)}</code>"
        )
    except Exception as e:
        tgbot.edit_message(
            token, chat_id, status_msg_id,
            f"❌ Failed to save audio file:\n<code>{escape_html(str(e))}</code>"
        )


def enqueue_job(token, chat_id, job_fn, label="Queued"):
    """Enqueue a music download job and notify the user of queue position."""
    pos = job_queue.qsize() + (1 if is_downloading else 0)
    job_queue.put(job_fn)
    if pos > 0:
        tgbot.send(token, chat_id, f"⏳ <b>{escape_html(label)}</b>\nQueue position: <b>#{pos}</b>")


def get_music_status():
    """Return status of music background queue and currently downloading job."""
    with _music_lock:
        active = dict(current_job_info)
    return {
        "is_downloading": is_downloading,
        "queue_size": job_queue.qsize(),
        "active_job": active,
    }
