"""
HomeLab Mirror Bot
Send a magnet/torrent link on Telegram -> added to qBittorrent.
/status, /downloading, /pause, /resume
"""

import requests

from shared import tgbot
from shared.config import load_config


def qbit_session(cfg):
    q = cfg["qbittorrent"]
    s = requests.Session()
    s.post(q["host"] + "/api/v2/auth/login", data={
        "username": q["user"],
        "password": q["pass"],
    }, timeout=10)
    return s


def add_magnet(cfg, magnet, category):
    q = cfg["qbittorrent"]
    s = qbit_session(cfg)
    r = s.post(q["host"] + "/api/v2/torrents/add", data={
        "urls": magnet,
        "savepath": cfg["paths"]["downloads_completed"],
        "category": category,
    }, timeout=15)
    return r.text.strip() == "Ok."


def get_torrents(cfg, filter=None):
    q = cfg["qbittorrent"]
    s = qbit_session(cfg)
    url = q["host"] + "/api/v2/torrents/info"
    if filter:
        url += "?filter=" + filter
    return s.get(url, timeout=15).json()


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
        tgbot.send(token, chat_id, "Send a magnet link or use /start")
        return

    text = msg["text"].strip()

    if text == "/start":
        tgbot.send(token, chat_id,
            "<b>HomeLab Mirror Bot</b>\n\n"
            "Send me a magnet link or HTTP torrent link.\n"
            "I will add it to qBittorrent automatically.\n\n"
            "Commands:\n"
            "/status - all torrents\n"
            "/downloading - active downloads\n"
            "/pause - pause all\n"
            "/resume - resume all"
        )
        return

    if text == "/status":
        try:
            torrents = get_torrents(cfg)
            if not torrents:
                tgbot.send(token, chat_id, "No torrents.")
                return
            out = "<b>All Torrents (" + str(len(torrents)) + ")</b>\n\n"
            for t in torrents[:8]:
                p = round(t["progress"] * 100, 1)
                name = t["name"][:45]
                size = round(t["size"] / (1024 ** 3), 2)
                state = t["state"]
                out += "<b>" + name + "</b>\n"
                out += str(p) + "% - " + str(size) + "GB - " + state + "\n\n"
            tgbot.send(token, chat_id, out)
        except Exception as e:
            tgbot.send(token, chat_id, "Error: " + str(e))
        return

    if text == "/downloading":
        try:
            torrents = get_torrents(cfg, filter="downloading")
            if not torrents:
                tgbot.send(token, chat_id, "Nothing downloading right now.")
                return
            out = "<b>Active Downloads:</b>\n\n"
            for t in torrents:
                p = round(t["progress"] * 100, 1)
                name = t["name"][:45]
                eta = t.get("eta", 0)
                if eta < 8640000:
                    eta_str = str(eta // 3600) + "h " + str((eta % 3600) // 60) + "m"
                else:
                    eta_str = "unknown"
                speed = round(t.get("dlspeed", 0) / (1024 ** 2), 2)
                out += "<b>" + name + "</b>\n"
                out += str(p) + "% - " + str(speed) + " MB/s - ETA: " + eta_str + "\n\n"
            tgbot.send(token, chat_id, out)
        except Exception as e:
            tgbot.send(token, chat_id, "Error: " + str(e))
        return

    if text == "/pause":
        try:
            s = qbit_session(cfg)
            s.post(cfg["qbittorrent"]["host"] + "/api/v2/torrents/pause",
                   data={"hashes": "all"}, timeout=10)
            tgbot.send(token, chat_id, "All torrents paused.")
        except Exception as e:
            tgbot.send(token, chat_id, "Error: " + str(e))
        return

    if text == "/resume":
        try:
            s = qbit_session(cfg)
            s.post(cfg["qbittorrent"]["host"] + "/api/v2/torrents/resume",
                   data={"hashes": "all"}, timeout=10)
            tgbot.send(token, chat_id, "All torrents resumed.")
        except Exception as e:
            tgbot.send(token, chat_id, "Error: " + str(e))
        return

    if text.startswith("magnet:") or text.startswith("http"):
        tgbot.send(token, chat_id, "Adding to qBittorrent...")
        lower = text.lower()
        if any(x in lower for x in ["s0", "s1", "s2", "s3", "season", "episode", "e0", "e1", "e2", "e3"]):
            category = "tv-sonarr"
            label = "TV Show"
        else:
            category = "radarr"
            label = "Movie"
        try:
            success = add_magnet(cfg, text, category)
        except Exception as e:
            tgbot.send(token, chat_id, "Error talking to qBittorrent: " + str(e))
            return
        if success:
            tgbot.send(token, chat_id,
                "<b>Added to qBittorrent!</b>\n"
                "Type: " + label + "\n"
                "Category: " + category + "\n\n"
                "Use /status to track progress."
            )
        else:
            tgbot.send(token, chat_id, "Failed to add. Is qBittorrent running?")
        return

    tgbot.send(token, chat_id, "Send a magnet link or use /start")


if __name__ == "__main__":
    tgbot.run_polling(
        get_token=lambda cfg: cfg["telegram"]["mirror_bot_token"],
        process_fn=process_update,
        bot_name="Mirror Bot",
    )
