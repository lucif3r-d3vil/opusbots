import pytest
from unittest.mock import MagicMock, patch
from bots import status_handler


def test_build_status_text(tmp_path):
    cfg = {
        "paths": {
            "downloads_completed": str(tmp_path / "Downloads"),
            "movies": str(tmp_path / "Movies"),
            "music": str(tmp_path / "Music"),
        },
        "qbittorrent": {"host": "http://qbit:8080", "user": "admin", "pass": "secret"}
    }

    with patch("bots.torrent_handler.get_torrents") as mock_torrents:
        mock_torrents.return_value = [
            {"name": "Torrent 1", "progress": 0.5, "state": "downloading", "dlspeed": 1024 * 1024, "eta": 120}
        ]

        text = status_handler.build_status_text(cfg)
        assert "OpusBots Unified Dashboard" in text
        assert "Storage Status" in text
        assert "qBittorrent" in text
        assert "Torrent 1" in text
        assert "Music Queue" in text


def test_build_status_keyboard():
    kb = status_handler.build_status_keyboard()
    assert "inline_keyboard" in kb
    assert any("Refresh" in btn["text"] for row in kb["inline_keyboard"] for btn in row)
