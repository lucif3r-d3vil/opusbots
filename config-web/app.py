"""
OpusBots Configuration & Administration Web Panel.

Allows live updating of Telegram Bot credentials, qBittorrent settings,
and media library storage paths, plus testing connections and container restarts.
"""

import os
from functools import wraps

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from bots.torrent_handler import test_qbit_connection
from shared import tgbot
from shared.config import get_bot_token, load_config, save_config

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "please-change-me-in-.env")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "changeme")

BOT_CONTAINERS = ["opus-bot", "config-web"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "")
        passwd = request.form.get("password", "")
        if user == ADMIN_USER and passwd == ADMIN_PASS:
            session["logged_in"] = True
            return redirect(url_for("index"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/", methods=["GET"])
@login_required
def index():
    cfg = load_config()
    # Normalize bot_token
    token = get_bot_token(cfg)
    return render_template("config.html", cfg=cfg, bot_token=token, containers=BOT_CONTAINERS)


@app.route("/save", methods=["POST"])
@login_required
def save():
    cfg = load_config()

    bot_token = request.form.get("bot_token", "").strip()
    cfg["telegram"]["bot_token"] = bot_token

    raw_uid = request.form.get("allowed_user_id", "").strip()
    try:
        cfg["telegram"]["allowed_user_id"] = int(raw_uid) if raw_uid else 0
    except ValueError:
        flash("Allowed Telegram User ID must be an integer.", "error")
        return redirect(url_for("index"))

    cfg["qbittorrent"]["host"] = request.form.get("qbit_host", "").strip()
    cfg["qbittorrent"]["user"] = request.form.get("qbit_user", "").strip()

    # Only overwrite password if a new value was provided
    new_pass = request.form.get("qbit_pass", "")
    if new_pass:
        cfg["qbittorrent"]["pass"] = new_pass

    cfg["paths"]["downloads_completed"] = request.form.get("path_downloads_completed", "").strip()
    cfg["paths"]["movies"] = request.form.get("path_movies", "").strip()
    cfg["paths"]["music"] = request.form.get("path_music", "").strip()

    save_config(cfg)
    flash("Configuration saved. OpusBot detects changes live within ~10-15s.", "success")
    return redirect(url_for("index"))


@app.route("/api/test-telegram", methods=["POST"])
@login_required
def test_telegram():
    """Test Telegram Bot Token via getMe API."""
    data = request.get_json(silent=True) or {}
    token = data.get("bot_token", "").strip()
    if not token:
        cfg = load_config()
        token = get_bot_token(cfg)

    if not token:
        return jsonify({"ok": False, "message": "No bot token provided or configured."})

    ok, res = tgbot.get_me(token)
    if ok:
        bot_user = res.get("username", "Unknown")
        bot_name = res.get("first_name", "Bot")
        return jsonify({
            "ok": True,
            "message": f"Connected successfully! Bot: @{bot_user} ({bot_name})",
            "bot_username": bot_user,
        })
    else:
        return jsonify({"ok": False, "message": f"Telegram API error: {res}"})


@app.route("/api/test-qbit", methods=["POST"])
@login_required
def test_qbit():
    """Test qBittorrent connection."""
    data = request.get_json(silent=True) or {}
    cfg = load_config()

    test_cfg = {
        "qbittorrent": {
            "host": data.get("host", "").strip() or cfg["qbittorrent"]["host"],
            "user": data.get("user", "").strip() if data.get("user") is not None else cfg["qbittorrent"]["user"],
            "pass": data.get("pass", "") if data.get("pass") else cfg["qbittorrent"]["pass"],
        }
    }

    ok, msg = test_qbit_connection(test_cfg)
    return jsonify({"ok": ok, "message": msg})


@app.route("/restart/<container>", methods=["POST"])
@login_required
def restart(container):
    if container not in BOT_CONTAINERS:
        flash("Unknown container requested.", "error")
        return redirect(url_for("index"))
    try:
        import docker
        client = docker.from_env()
        client.containers.get(container).restart(timeout=10)
        flash(f"Successfully restarted {container}.", "success")
    except Exception as e:
        flash(f"Could not restart {container}: {e}", "error")
    return redirect(url_for("index"))


@app.route("/restart-all", methods=["POST"])
@login_required
def restart_all():
    try:
        import docker
        client = docker.from_env()
        for name in BOT_CONTAINERS:
            try:
                client.containers.get(name).restart(timeout=10)
            except Exception as e:
                print(f"Error restarting {name}: {e}")
        flash("Restarted OpusBot and Config Web.", "success")
    except Exception as e:
        flash(f"Restart failed: {e}", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090)
