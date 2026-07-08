import os
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for

from shared.config import load_config, save_config

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "please-change-me-in-.env")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "changeme")

BOT_CONTAINERS = ["mirror-bot", "downloads-bot", "music-bot"]


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
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
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
    return render_template("config.html", cfg=cfg, containers=BOT_CONTAINERS)


@app.route("/save", methods=["POST"])
@login_required
def save():
    cfg = load_config()

    cfg["telegram"]["mirror_bot_token"] = request.form.get("mirror_bot_token", "").strip()
    cfg["telegram"]["downloads_bot_token"] = request.form.get("downloads_bot_token", "").strip()
    cfg["telegram"]["music_bot_token"] = request.form.get("music_bot_token", "").strip()

    raw_uid = request.form.get("allowed_user_id", "").strip()
    try:
        cfg["telegram"]["allowed_user_id"] = int(raw_uid) if raw_uid else 0
    except ValueError:
        flash("Allowed Telegram user ID must be a number.", "error")
        return redirect(url_for("index"))

    cfg["qbittorrent"]["host"] = request.form.get("qbit_host", "").strip()
    cfg["qbittorrent"]["user"] = request.form.get("qbit_user", "").strip()
    # Only overwrite the password if the user actually typed a new one,
    # so the masked field doesn't blank it out on every save.
    new_pass = request.form.get("qbit_pass", "")
    if new_pass:
        cfg["qbittorrent"]["pass"] = new_pass

    cfg["paths"]["downloads_completed"] = request.form.get("path_downloads_completed", "").strip()
    cfg["paths"]["movies"] = request.form.get("path_movies", "").strip()
    cfg["paths"]["music"] = request.form.get("path_music", "").strip()

    save_config(cfg)
    flash("Saved. Bots poll for config changes automatically within ~15s.", "success")
    return redirect(url_for("index"))


@app.route("/restart/<container>", methods=["POST"])
@login_required
def restart(container):
    if container not in BOT_CONTAINERS:
        flash("Unknown container.", "error")
        return redirect(url_for("index"))
    try:
        import docker
        client = docker.from_env()
        client.containers.get(container).restart(timeout=10)
        flash(f"Restarted {container}.", "success")
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
            client.containers.get(name).restart(timeout=10)
        flash("Restarted all bots.", "success")
    except Exception as e:
        flash(f"Restart failed: {e}", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090)
