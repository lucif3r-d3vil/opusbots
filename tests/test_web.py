import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.abspath("config-web"))
import app as web_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    web_app.app.config["TESTING"] = True
    web_app.app.config["SECRET_KEY"] = "test-secret"
    web_app.ADMIN_USER = "admin"
    web_app.ADMIN_PASS = "secret123"

    cfg_file = str(tmp_path / "config.json")
    from shared import config
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)
    web_app._login_attempts.clear()

    with web_app.app.test_client() as client:
        yield client


def test_login_and_logout(client):
    # Unauthenticated redirect
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    # Login POST invalid
    resp = client.post("/login", data={"username": "admin", "password": "wrongpassword"})
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data

    # Login POST valid
    resp = client.post("/login", data={"username": "admin", "password": "secret123"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Telegram Bot" in resp.data

    # Logout
    resp = client.get("/logout", follow_redirects=True)
    assert resp.status_code == 200
    assert b"sign in" in resp.data


def test_save_configuration(client):
    # Login first
    client.post("/login", data={"username": "admin", "password": "secret123"})

    save_data = {
        "bot_token": "987654:TEST_NEW_TOKEN",
        "allowed_user_id": "123456789",
        "qbit_host": "http://192.168.1.100:8080",
        "qbit_user": "admin",
        "qbit_pass": "  qbitpass  ",
        "qbit_verify_tls": "1",
        "path_downloads_completed": "/tank/Downloads/Completed",
        "path_movies": "/tank/Movies",
        "path_music": "/tank/Music",
    }
    resp = client.post("/save", data=save_data, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Configuration saved" in resp.data

    from shared.config import load_config
    cfg = load_config()
    assert cfg["telegram"]["bot_token"] == "987654:TEST_NEW_TOKEN"
    assert cfg["telegram"]["allowed_user_id"] == 123456789
    # A pasted URL is split into Radarr-style host + port on save.
    assert cfg["qbittorrent"]["host"] == "http://192.168.1.100"
    assert cfg["qbittorrent"]["port"] == "8080"
    assert cfg["qbittorrent"]["pass"] == "qbitpass"
    assert cfg["qbittorrent"]["verify_tls"] is True


def test_save_radarr_style_host_and_port(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})
    resp = client.post("/save", data={
        "bot_token": "1:t", "allowed_user_id": "1",
        "qbit_host": "192.168.1.50", "qbit_port": "30024",
        "qbit_user": "admin", "qbit_pass": "pw",
        "path_downloads_completed": "/tank/Downloads/Completed",
        "path_movies": "/tank/Movies", "path_music": "/tank/Music",
    }, follow_redirects=True)
    assert b"Configuration saved" in resp.data

    from shared.config import load_config
    cfg = load_config()
    assert cfg["qbittorrent"]["host"] == "192.168.1.50"
    assert cfg["qbittorrent"]["port"] == "30024"


def test_save_rejects_bad_port_and_relative_paths(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})

    resp = client.post("/save", data={"bot_token": "1:t", "qbit_host": "10.0.0.5", "qbit_port": "not-a-port"},
                       follow_redirects=True)
    assert b"not a number" in resp.data

    resp = client.post("/save", data={"bot_token": "1:t", "qbit_host": "10.0.0.5", "qbit_port": "8080",
                                      "path_movies": "tank/Movies"}, follow_redirects=True)
    assert b"absolute path" in resp.data


def test_blank_password_keeps_the_stored_one(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})
    client.post("/save", data={"bot_token": "1:t", "qbit_host": "10.0.0.5", "qbit_port": "8080",
                               "qbit_user": "admin", "qbit_pass": "keep-me"})
    client.post("/save", data={"bot_token": "1:t", "qbit_host": "10.0.0.5", "qbit_port": "8080",
                               "qbit_user": "admin", "qbit_pass": ""})

    from shared.config import load_config
    assert load_config()["qbittorrent"]["pass"] == "keep-me"


def test_verify_tls_checkbox_can_be_disabled(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})
    # The template always posts the hidden "0" field; the checkbox adds "1".
    client.post("/save", data={"bot_token": "1:t", "qbit_host": "10.0.0.5", "qbit_verify_tls": "0"})
    from shared.config import load_config
    assert load_config()["qbittorrent"]["verify_tls"] is False


def test_test_telegram_api(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})

    with patch("shared.tgbot.get_me") as mock_get_me:
        mock_get_me.return_value = (True, {"username": "TestOpusBot", "first_name": "Opus"})
        resp = client.post("/api/test-telegram", json={"bot_token": "valid_token"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "@TestOpusBot" in data["message"]


def _report(ok=True, message="Connected to qBittorrent v5.1.0 (Web API 2.11.4) at http://qbit.local:8080",
            hint="", base_url="http://qbit.local:8080", version="v5.1.0"):
    return {"ok": ok, "message": message, "hint": hint, "base_url": base_url,
            "version": version, "api_version": "2.11.4", "auth_bypassed": False}


def test_test_qbit_api(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})

    with patch.object(web_app.qbittorrent, "diagnose", return_value=_report()) as mock_diag:
        resp = client.post("/api/test-qbit", json={"host": "http://qbit.local:8080", "user": "admin", "pass": "pass"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "Connected to qBittorrent" in data["message"]
        assert data["base_url"] == "http://qbit.local:8080"
        # A manual test must ignore the login back-off timer.
        assert mock_diag.call_args.kwargs["force_fresh"] is True


def test_test_qbit_api_reports_hints_and_normalised_url(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})
    report = _report(ok=False, message="qBittorrent rejected the username or password.",
                     hint="Re-check them in qBittorrent.", base_url="http://192.168.1.50:30024", version="")
    with patch.object(web_app.qbittorrent, "diagnose", return_value=report):
        resp = client.post("/api/test-qbit", json={"qbit_host": "192.168.1.50", "qbit_port": "30024",
                                                   "qbit_user": "admin", "qbit_pass": "pw"})
        data = resp.get_json()
        assert data["ok"] is False
        assert data["hint"].startswith("Re-check")
        assert data["base_url"] == "http://192.168.1.50:30024"


def test_test_qbit_does_not_poke_a_banned_server(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})
    banned_report = _report(ok=False,
                            message="Your IP address has been banned after too many failed attempts.",
                            hint="Wait for the ban to expire.", base_url="http://10.0.0.5:8080", version="")
    with patch.object(web_app.qbittorrent, "active_ban", return_value=420) as mock_ban, \
         patch.object(web_app.qbittorrent, "diagnose", return_value=banned_report) as mock_diag:
        resp = client.post("/api/test-qbit", json={"qbit_host": "10.0.0.5", "qbit_port": "8080"})
        data = resp.get_json()
        assert data["ok"] is False
        assert "banned" in data["message"]
        mock_ban.assert_called_once()
        # Another login attempt would only restart qBittorrent's ban timer.
        assert mock_diag.call_args.kwargs["force_fresh"] is False


def test_test_qbit_api_without_host(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})
    resp = client.post("/api/test-qbit", json={"qbit_host": ""})
    data = resp.get_json()
    assert data["ok"] is False
    assert "Host and Port" in data["message"]


def test_healthz_is_open(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_login_is_throttled(client):
    for _ in range(web_app.LOGIN_MAX_ATTEMPTS):
        client.post("/login", data={"username": "admin", "password": "wrong"})
    resp = client.post("/login", data={"username": "admin", "password": "secret123"})
    assert resp.status_code == 429
    assert b"Too many failed sign-in attempts" in resp.data


def test_security_headers(client):
    resp = client.get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in resp.headers


def test_restart_routes(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})

    # Unknown container
    resp = client.post("/restart/fake-bot", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Unknown container requested" in resp.data
