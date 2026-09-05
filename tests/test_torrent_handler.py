import pytest
from unittest.mock import MagicMock, patch
from bots import torrent_handler


def test_detect_category():
    cat, label = torrent_handler.detect_category("Breaking.Bad.S01E05.1080p.mkv")
    assert cat == "tv-sonarr"
    assert "TV Show" in label

    cat, label = torrent_handler.detect_category("Stranger.Things.Season.4.Complete")
    assert cat == "tv-sonarr"

    cat, label = torrent_handler.detect_category("Inception.2010.1080p.BluRay.x264")
    assert cat == "radarr"
    assert "Movie" in label


def test_is_torrent_or_magnet():
    assert torrent_handler.is_torrent_or_magnet("magnet:?xt=urn:btih:1234567890abcdef")
    assert torrent_handler.is_torrent_or_magnet("https://example.com/file.torrent")
    assert not torrent_handler.is_torrent_or_magnet("https://youtube.com/watch?v=123")
    assert not torrent_handler.is_torrent_or_magnet("just plain text")


def test_qbit_session_and_add_magnet():
    cfg = {
        "qbittorrent": {"host": "http://qbit:8080", "user": "admin", "pass": "secret"},
        "paths": {"downloads_completed": "/tank/Downloads/Completed"},
    }

    with patch("requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # Login response
        login_resp = MagicMock()
        login_resp.text = "Ok."
        login_resp.status_code = 200

        # Add torrent response
        add_resp = MagicMock()
        add_resp.text = "Ok."
        add_resp.status_code = 200

        mock_session.post.side_effect = [login_resp, add_resp]

        success = torrent_handler.add_magnet(cfg, "magnet:?xt=urn:btih:xyz", category="radarr")
        assert success is True


def test_add_torrent_file():
    cfg = {
        "qbittorrent": {"host": "http://qbit:8080", "user": "admin", "pass": "secret"},
        "paths": {"downloads_completed": "/tank/Downloads/Completed"},
    }

    with patch("requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        login_resp = MagicMock()
        login_resp.text = "Ok."
        login_resp.status_code = 200

        add_resp = MagicMock()
        add_resp.text = "Ok."
        add_resp.status_code = 200

        mock_session.post.side_effect = [login_resp, add_resp]

        success = torrent_handler.add_torrent_file(cfg, b"fake_torrent_bytes", "test.torrent", category="radarr")
        assert success is True


def test_format_torrents_status():
    torrents = [
        {
            "name": "Ubuntu 24.04 ISO",
            "progress": 0.75,
            "size": 1024 * 1024 * 1024 * 4,
            "state": "downloading",
            "dlspeed": 1024 * 1024 * 12,
            "eta": 300,
            "category": "linux",
        }
    ]

    out = torrent_handler.format_torrents_status(torrents, active_only=True)
    assert "Ubuntu 24.04 ISO" in out
    assert "75.0%" in out
    assert "linux" in out
