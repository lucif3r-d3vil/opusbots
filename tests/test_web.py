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
        "qbit_pass": "qbitpass",
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
    assert cfg["qbittorrent"]["host"] == "http://192.168.1.100:8080"


def test_test_telegram_api(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})

    with patch("shared.tgbot.get_me") as mock_get_me:
        mock_get_me.return_value = (True, {"username": "TestOpusBot", "first_name": "Opus"})
        resp = client.post("/api/test-telegram", json={"bot_token": "valid_token"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "@TestOpusBot" in data["message"]


def test_test_qbit_api(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})

    with patch.object(web_app, "test_qbit_connection", return_value=(True, "Connected to qBittorrent v4.6.0")):
        resp = client.post("/api/test-qbit", json={"host": "http://qbit.local:8080", "user": "admin", "pass": "pass"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "Connected to qBittorrent" in data["message"]


def test_restart_routes(client):
    client.post("/login", data={"username": "admin", "password": "secret123"})

    # Unknown container
    resp = client.post("/restart/fake-bot", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Unknown container requested" in resp.data
