"""
OpusBots Configuration & Administration Web Panel.

Allows live updating of Telegram Bot credentials, qBittorrent settings,
and media library storage paths, plus testing connections and container restarts.
"""

import hmac
import os
import secrets
import time
from datetime import timedelta
from functools import wraps

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from shared import qbittorrent, tgbot
from shared import config as shared_config
from shared.config import get_allowed_user_id, get_bot_token, load_config, save_config
from shared.qbittorrent import split_host_port

def _truthy(value):
    """Form/env values like "0", "false", "off" and "" are False; anything else is True."""
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


def _flag(name):
    return _truthy(os.environ.get(name, "0"))


app = Flask(__name__)
DEFAULT_SECRET_KEY = "please-change-me-in-.env"
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or DEFAULT_SECRET_KEY

# Set COOKIE_SAMESITE=None + COOKIE_SECURE=1 when the panel is served over HTTPS
# inside an iframe (Cloudflare Access, a dashboard like Homarr, or a preview proxy).
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "Lax").strip() or None
ALLOW_EMBEDDING = _flag("ALLOW_EMBEDDING")
# Only trust X-Forwarded-For (for the login throttle) behind a reverse proxy you control.
TRUST_PROXY = _flag("TRUST_PROXY")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE=_flag("COOKIE_SECURE"),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "changeme")
INSECURE_DEFAULT_PASSWORDS = {"", "changeme", "change-me-to-something-strong", "admin", "password"}

BOT_CONTAINERS = ["opus-bot", "config-web"]

# Very small brute-force guard for the login page.
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 300
_login_attempts = {}


def _client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "") if TRUST_PROXY else ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _recent_attempts(ip):
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[ip] = attempts
    return attempts


def _throttled(ip):
    """Return seconds left in the lockout window, 0 when allowed to try."""
    attempts = _recent_attempts(ip)
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        return int(LOGIN_WINDOW_SECONDS - (time.time() - attempts[0])) + 1
    return 0


def _record_attempt(ip):
    _recent_attempts(ip).append(time.time())


def admin_password_is_insecure():
    return ADMIN_PASS.strip().lower() in INSECURE_DEFAULT_PASSWORDS


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    csp = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; base-uri 'self'; form-action 'self'"
    )
    if not ALLOW_EMBEDDING:
        response.headers.setdefault("X-Frame-Options", "DENY")
        csp += "; frame-ancestors 'none'"
    response.headers.setdefault("Content-Security-Policy", csp)
    return response


@app.before_request
def reject_cross_site_posts():
    """Lightweight CSRF guard: browsers label requests started by other sites."""
    if request.method == "POST" and request.headers.get("Sec-Fetch-Site") == "cross-site":
        return "Cross-site request blocked.", 403


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
        ip = _client_ip()
        wait = _throttled(ip)
        if wait:
            flash(f"Too many failed sign-in attempts. Try again in {wait}s.", "error")
            return render_template("login.html"), 429

        user = request.form.get("username", "")
        passwd = request.form.get("password", "")
        user_ok = hmac.compare_digest(user.encode("utf-8"), ADMIN_USER.encode("utf-8"))
        pass_ok = hmac.compare_digest(passwd.encode("utf-8"), ADMIN_PASS.encode("utf-8"))
        if user_ok and pass_ok:
            _login_attempts.pop(ip, None)
            session.permanent = True
            session["logged_in"] = True
            return redirect(url_for("index"))

        _record_attempt(ip)
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/healthz")
def healthz():
    """Unauthenticated liveness probe for Docker/compose healthchecks."""
    return jsonify({"ok": True, "service": "opusbots-config-web"})


@app.route("/", methods=["GET"])
@login_required
def index():
    cfg = load_config()
    token = get_bot_token(cfg)
    qbit = cfg.get("qbittorrent", {})
    return render_template(
        "config.html",
        cfg=cfg,
        bot_token=token,
        containers=BOT_CONTAINERS,
        qbit_url=qbittorrent.get_configured_url(cfg),
        verify_tls=_truthy(qbit.get("verify_tls", True)),
        setup={
            "token": bool(token),
            "user": get_allowed_user_id(cfg) != 0,
            "qbit": bool(qbit.get("host")),
        },
        weak_admin_password=admin_password_is_insecure(),
    )


def _read_qbit_form(cfg):
    """Merge the posted qBittorrent fields over the stored config.

    Returns ``(qbit_dict, error_message)``.  The password field is write-only in
    the UI: leaving it blank keeps whatever is already stored.
    """
    stored = cfg.get("qbittorrent", {}) or {}
    data = request.get_json(silent=True) if request.is_json else request.form

    def field(names, fallback=""):
        """First present value wins; accepts the legacy short names too
        ("host" as well as "qbit_host") so old scripts keep working."""
        for name in names:
            value = data.get(name)
            if value is not None:
                return str(value)
        return str(fallback or "")

    host = field(("qbit_host", "host"), stored.get("host", "")).strip()
    port = field(("qbit_port", "port"), stored.get("port", "")).strip()

    # Let people paste "192.168.1.50:30024" (or a full URL) into the host box.
    if host:
        host_only, host_port = split_host_port(host)
        if host_port and not port:
            host, port = host_only, host_port

    if port:
        try:
            port_number = int(port)
        except ValueError:
            return None, f"qBittorrent port '{port}' is not a number."
        if not 1 <= port_number <= 65535:
            return None, f"qBittorrent port '{port_number}' is out of range (1-65535)."
        port = str(port_number)

    if host:
        try:
            qbittorrent.build_base_url(host, port, field(("qbit_url_base", "url_base"), stored.get("url_base", "")).strip())
        except qbittorrent.QBitError as exc:
            return None, exc.full

    user = field(("qbit_user", "user"), stored.get("user", "")).strip()
    password = data.get("qbit_pass")
    if password is None:
        password = data.get("pass")
    if password is None or str(password) == "":
        password = stored.get("pass", "")
    password = str(password).strip()

    verify = data.get("qbit_verify_tls")
    if verify is None:
        verify = data.get("verify_tls", stored.get("verify_tls", True))

    return {
        "host": host,
        "port": port,
        "url_base": field(("qbit_url_base", "url_base"), stored.get("url_base", "")).strip(),
        "user": user,
        "pass": password,
        "verify_tls": _truthy(verify),
    }, ""


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

    qbit, error = _read_qbit_form(cfg)
    if error:
        flash(error, "error")
        return redirect(url_for("index"))
    cfg["qbittorrent"] = qbit

    for key, form_name in (
        ("downloads_completed", "path_downloads_completed"),
        ("movies", "path_movies"),
        ("music", "path_music"),
    ):
        value = request.form.get(form_name, "").strip()
        if value and not value.startswith("/"):
            flash(f"'{form_name}' must be an absolute path inside the container (e.g. /tank/Movies).", "error")
            return redirect(url_for("index"))
        if value:
            cfg["paths"][key] = value

    save_config(cfg)
    # Drop cached qBittorrent sessions so the new address/credentials are used
    # on the very next Telegram command instead of after a container restart.
    qbittorrent.clear_client_cache(clear_backoff=False)

    if not qbit["host"]:
        flash("Saved. qBittorrent host is empty -- torrent features stay disabled until you set it.", "warn")
    else:
        flash("Configuration saved. OpusBot detects changes live within ~10-15s.", "success")
    return redirect(url_for("index"))


@app.route("/api/test-telegram", methods=["POST"])
@login_required
def test_telegram():
    """Test Telegram Bot Token via getMe API."""
    data = request.get_json(silent=True) or {}
    token = str(data.get("bot_token", "") or "").strip()
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
    """Test the qBittorrent connection and explain exactly what went wrong."""
    cfg = load_config()
    qbit, error = _read_qbit_form(cfg)
    if error:
        return jsonify({"ok": False, "message": error})
    if not qbit["host"]:
        return jsonify({
            "ok": False,
            "message": "No qBittorrent host set. Enter the same Host and Port you use in Radarr/Sonarr.",
        })

    # A manual test always gets a real answer -- unless qBittorrent has already
    # banned this IP, in which case another login attempt would only restart the
    # ban timer.  Then we report the recorded ban (with its countdown) instead.
    banned_for = qbittorrent.active_ban({"qbittorrent": qbit})
    report = qbittorrent.diagnose({"qbittorrent": qbit}, force_fresh=not banned_for)
    return jsonify({
        "ok": report["ok"],
        "message": report["message"],
        "hint": report.get("hint", ""),
        "base_url": report.get("base_url", ""),
        "version": report.get("version", ""),
    })


def _restart(names):
    """Restart containers through the Docker socket. Returns a list of error strings."""
    try:
        import docker
        client = docker.from_env()
    except Exception as exc:
        return [f"Docker is not reachable ({exc}). Is /var/run/docker.sock mounted into config-web?"]
    errors = []
    for name in names:
        try:
            client.containers.get(name).restart(timeout=10)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return errors


@app.route("/restart/<container>", methods=["POST"])
@login_required
def restart(container):
    if container not in BOT_CONTAINERS:
        flash("Unknown container requested.", "error")
        return redirect(url_for("index"))
    errors = _restart([container])
    if errors:
        flash(f"Could not restart {container}: {errors[0]}", "error")
    else:
        flash(f"Successfully restarted {container}.", "success")
    return redirect(url_for("index"))


@app.route("/restart-all", methods=["POST"])
@login_required
def restart_all():
    errors = _restart(BOT_CONTAINERS)
    if errors:
        flash("Restart problems:\n" + "\n".join(errors), "error")
    else:
        flash("Restarted OpusBot and Config Web.", "success")
    return redirect(url_for("index"))


def _persisted_secret(filename, make):
    """Return a secret kept in the config volume so it survives restarts."""
    path = os.path.join(os.path.dirname(shared_config.CONFIG_PATH) or ".", filename)
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
        if value:
            return value
    except OSError:
        pass
    value = make()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError as exc:
        print(f"[config-web] Could not persist {filename} ({exc}); it will change on restart.")
    return value


def init_credentials():
    """Never run with the publicly known defaults: generate and persist strong ones."""
    global ADMIN_PASS
    if app.secret_key == DEFAULT_SECRET_KEY:
        app.secret_key = _persisted_secret(".flask_secret", lambda: secrets.token_hex(32))
    if not os.environ.get("ADMIN_PASS", "").strip():
        ADMIN_PASS = _persisted_secret(".admin_password", lambda: secrets.token_urlsafe(12))
        print(
            f"[config-web] ADMIN_PASS is not set, so a password was generated.\n"
            f"[config-web]   Sign in with  user: {ADMIN_USER}   password: {ADMIN_PASS}\n"
            f"[config-web]   (stored in {os.path.dirname(shared_config.CONFIG_PATH)}/.admin_password; "
            f"set ADMIN_PASS in .env to choose your own)"
        )


if __name__ == "__main__":
    init_credentials()
    if admin_password_is_insecure():
        print("[config-web] WARNING: ADMIN_PASS is a default value; set a strong one in .env.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8090")))
