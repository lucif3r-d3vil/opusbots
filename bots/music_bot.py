"""
HomeLab Music Bot
/yt URL, /flac URL, /playlist URL, /search artist - song, or just paste a link.
"""

import queue
import re
import subprocess
import threading
import time

from shared import tgbot
from shared.config import load_config

# Jobs are plain zero-arg callables; a single worker thread runs them one at a
# time so downloads never overlap, and anything queued behind a running job
# actually gets picked up and run once it finishes (unlike the old version,
# where queued items were appended but nothing ever drained the list).
job_queue = queue.Queue()
is_downloading = False


def queue_worker():
    """Runs forever in a background thread, executing queued jobs one at a time."""
    while True:
        job = job_queue.get()
        try:
            job()
        except Exception as e:
            print(f"queue worker error: {e}")
        finally:
            job_queue.task_done()


def progress_bar(percent, width=10):
    filled = int(width * percent / 100)
    return "\u2588" * filled + "\u2591" * (width - filled)


def parse_progress(line):
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


def _run_ytdlp_with_progress(token, chat_id, cmd, title, artist, duration, msg_id):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    last_edit = 0
    percent = 0
    speed = ""
    eta = ""
    size = ""

    for line in iter(process.stdout.readline, ""):
        line = line.strip()
        p = parse_progress(line)
        if p:
            percent, speed, eta, size = p["percent"], p["speed"], p["eta"], p["size"]

        now = time.time()
        if msg_id and now - last_edit > 2:
            bar = progress_bar(percent)
            spd = speed if speed else "Converting..."
            eta_str = "  ETA: " + eta if eta else ""
            tgbot.edit_message(token, chat_id, msg_id,
                "<b>" + title + "</b>\n"
                "By: " + artist + " | " + duration + "\n\n"
                "[" + bar + "] " + str(round(percent, 1)) + "%\n"
                "Size: " + size + "  Speed: " + spd + eta_str
            )
            last_edit = now

    process.wait()
    return process.returncode


def download_song(token, cfg, chat_id, url, quality="mp3"):
    global is_downloading
    is_downloading = True
    msg_id = tgbot.send(token, chat_id, "Fetching info...")

    try:
        info_cmd = ["yt-dlp", "--print", "%(title)s|||%(uploader)s|||%(duration_string)s",
                    "--no-playlist", url]
        info = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)

        title, artist, duration = "Unknown", "Unknown", "?"
        if info.returncode == 0 and "|||" in info.stdout:
            parts = info.stdout.strip().split("|||")
            if len(parts) >= 1:
                title = parts[0]
            if len(parts) >= 2:
                artist = parts[1]
            if len(parts) >= 3:
                duration = parts[2]

        audio_format = "flac" if quality == "flac" else "mp3"
        music_path = cfg["paths"]["music"]
        output_template = music_path + "/%(uploader)s/%(album,uploader)s/%(title)s.%(ext)s"

        cmd = ["yt-dlp", "-f", "bestaudio/best", "--extract-audio",
               "--audio-format", audio_format, "--audio-quality", "0",
               "--embed-thumbnail", "--embed-metadata", "--add-metadata",
               "--newline", "-o", output_template, url]

        rc = _run_ytdlp_with_progress(token, chat_id, cmd, title, artist, duration, msg_id)

        if rc == 0:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id,
                    "<b>" + title + "</b>\nBy: " + artist + "\n\n"
                    "[██████████] 100%\n\nDone! Saved to Music library."
                )
        else:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, "Download failed for: " + title)

    except Exception as e:
        print("download_song error: " + str(e))
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, "Error: " + str(e))
    finally:
        is_downloading = False


def download_playlist(token, cfg, chat_id, url):
    global is_downloading
    is_downloading = True
    msg_id = tgbot.send(token, chat_id, "Fetching playlist info...")

    try:
        info_cmd = ["yt-dlp", "--print", "%(playlist_title)s|||%(playlist_count)s",
                    "--playlist-items", "1", url]
        info = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)

        playlist_title, total_count = "Playlist", 0
        if info.returncode == 0 and "|||" in info.stdout:
            parts = info.stdout.strip().split("|||")
            if len(parts) >= 1:
                playlist_title = parts[0]
            if len(parts) >= 2:
                try:
                    total_count = int(parts[1])
                except Exception:
                    total_count = 0

        music_path = cfg["paths"]["music"]
        output_template = music_path + "/%(uploader)s/%(playlist_title)s/%(playlist_index)s - %(title)s.%(ext)s"

        cmd = ["yt-dlp", "-f", "bestaudio/best", "--extract-audio",
               "--audio-format", "mp3", "--audio-quality", "0",
               "--embed-thumbnail", "--embed-metadata", "--add-metadata",
               "--newline", "-o", output_template, url]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        last_edit = 0
        current_song = ""
        current_index = 0
        song_percent = 0
        speed = ""
        eta = ""

        for line in iter(process.stdout.readline, ""):
            line = line.strip()

            idx_match = re.search(r'\[download\] Downloading item (\d+) of (\d+)', line)
            if idx_match:
                current_index = int(idx_match.group(1))
                if total_count == 0:
                    total_count = int(idx_match.group(2))
                song_percent = 0

            dest_match = re.search(r'\[download\] Destination:.+?(\d+)\s+-\s+(.+?)\.(mp3|flac|m4a|webm|opus)', line)
            if dest_match:
                current_song = dest_match.group(2)[:35]

            p = parse_progress(line)
            if p:
                song_percent, speed, eta = p["percent"], p["speed"], p["eta"]

            now = time.time()
            if msg_id and now - last_edit > 2:
                overall = round((current_index / total_count * 100) if total_count > 0 else 0, 1)
                overall_bar = progress_bar(overall)
                song_bar = progress_bar(song_percent)
                spd = speed if speed else "Converting..."
                eta_str = "  ETA: " + eta if eta else ""
                tgbot.edit_message(token, chat_id, msg_id,
                    "<b>" + playlist_title + "</b>\n\n"
                    "Overall: [" + overall_bar + "] " + str(overall) + "%\n"
                    "Song " + str(current_index) + " / " + str(total_count) + "\n\n"
                    "Now: " + current_song + "\n"
                    "[" + song_bar + "] " + str(round(song_percent, 1)) + "%\n"
                    "Speed: " + spd + eta_str
                )
                last_edit = now

        process.wait()

        if process.returncode == 0:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id,
                    "<b>" + playlist_title + "</b>\n\n"
                    "Overall: [██████████] 100%\n"
                    "Song " + str(total_count) + " / " + str(total_count) + "\n\n"
                    "All done! Saved to Music library."
                )
        else:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, "Playlist download incomplete. Some songs may have failed.")

    except Exception as e:
        print("download_playlist error: " + str(e))
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, "Error: " + str(e))
    finally:
        is_downloading = False


def search_and_download(token, cfg, chat_id, query, quality="mp3"):
    global is_downloading
    is_downloading = True
    msg_id = tgbot.send(token, chat_id, "Searching: <b>" + query + "</b>")

    try:
        info_cmd = ["yt-dlp", "--print",
                    "%(title)s|||%(uploader)s|||%(duration_string)s|||%(webpage_url)s",
                    "--no-playlist", "ytsearch1:" + query + " audio"]
        info = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)

        if info.returncode != 0 or "|||" not in info.stdout:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, "Could not find: " + query)
            is_downloading = False
            return

        parts = info.stdout.strip().split("|||")
        title = parts[0] if len(parts) > 0 else query
        artist = parts[1] if len(parts) > 1 else "Unknown"
        duration = parts[2] if len(parts) > 2 else "?"
        found_url = parts[3] if len(parts) > 3 else ""

        if not found_url:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, "Could not find URL for: " + query)
            is_downloading = False
            return

        audio_format = "flac" if quality == "flac" else "mp3"
        music_path = cfg["paths"]["music"]
        output_template = music_path + "/%(uploader)s/%(album,uploader)s/%(title)s.%(ext)s"

        cmd = ["yt-dlp", "-f", "bestaudio/best", "--extract-audio",
               "--audio-format", audio_format, "--audio-quality", "0",
               "--embed-thumbnail", "--embed-metadata", "--add-metadata",
               "--newline", "-o", output_template, found_url]

        rc = _run_ytdlp_with_progress(token, chat_id, cmd, title, artist, duration, msg_id)

        if rc == 0:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id,
                    "<b>" + title + "</b>\nBy: " + artist + "\n\n"
                    "[██████████] 100%\n\nDone! Saved to Music library."
                )
        else:
            if msg_id:
                tgbot.edit_message(token, chat_id, msg_id, "Download failed for: " + title)

    except Exception as e:
        print("search_and_download error: " + str(e))
        if msg_id:
            tgbot.edit_message(token, chat_id, msg_id, "Error: " + str(e))
    finally:
        is_downloading = False


def process_update(update, cfg, token):
    if "message" not in update:
        return

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    allowed = cfg["telegram"]["allowed_user_id"]

    if not allowed or user_id != allowed:
        tgbot.send(token, chat_id, "Unauthorized.")
        return

    if "text" not in msg:
        tgbot.send(token, chat_id, "Send a command or YouTube URL.")
        return

    text = msg["text"].strip()

    if text in ["/start", "/help"]:
        tgbot.send(token, chat_id,
            "<b>HomeLab Music Bot</b>\n\n"
            "/yt URL - Download song (MP3)\n"
            "/flac URL - Download song (FLAC)\n"
            "/playlist URL - Download full playlist\n"
            "/search artist - song - Search and download\n"
            "/status - Download status\n\n"
            "Or just paste any YouTube URL!"
        )
        return

    if text == "/status":
        status = "Currently downloading." if is_downloading else "Idle. Ready."
        tgbot.send(token, chat_id, status + "\nQueue: " + str(job_queue.qsize()) + " pending.")
        return

    def enqueue(job, label):
        position = job_queue.qsize() + (1 if is_downloading else 0)
        job_queue.put(job)
        if position > 0:
            tgbot.send(token, chat_id, f"{label} Queue position: {position}.")

    if text.startswith("/yt "):
        url = text[4:].strip()
        enqueue(lambda u=url, c=chat_id: download_song(token, cfg, c, u, "mp3"), "Queued.")
        return

    if text.startswith("/flac "):
        url = text[6:].strip()
        enqueue(lambda u=url, c=chat_id: download_song(token, cfg, c, u, "flac"), "Queued (FLAC).")
        return

    if text.startswith("/playlist "):
        url = text[10:].strip()
        enqueue(lambda u=url, c=chat_id: download_playlist(token, cfg, c, u), "Playlist queued.")
        return

    if text.startswith("/search "):
        query = text[8:].strip()
        enqueue(lambda q=query, c=chat_id: search_and_download(token, cfg, c, q), "Search queued.")
        return

    if "youtube.com" in text or "youtu.be" in text or "music.youtube.com" in text:
        enqueue(lambda u=text, c=chat_id: download_song(token, cfg, c, u, "mp3"), "Queued.")
        return

    tgbot.send(token, chat_id, "Send a YouTube URL or use /help")


if __name__ == "__main__":
    threading.Thread(target=queue_worker, daemon=True).start()
    tgbot.run_polling(
        get_token=lambda cfg: cfg["telegram"]["music_bot_token"],
        process_fn=process_update,
        bot_name="Music Bot",
    )
