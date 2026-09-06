import pytest
from unittest.mock import MagicMock, patch

from bots import torrent_handler
from shared import qbittorrent

CFG = {
    "qbittorrent": {"host": "http://qbit:8080", "port": "", "user": "admin", "pass": "secret"},
    "paths": {"downloads_completed": "/tank/Downloads/Completed"},
}


@pytest.fixture(autouse=True)
def clean_cache():
    qbittorrent.clear_client_cache()
    yield
    qbittorrent.clear_client_cache()


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
    assert not torrent_handler.is_torrent_or_magnet("")


def test_add_magnet_passes_savepath_and_category():
    with patch.object(torrent_handler, "client") as mock_client:
        qbit = MagicMock()
        qbit.add_urls.return_value = True
        mock_client.return_value = qbit

        assert torrent_handler.add_magnet(CFG, "magnet:?xt=urn:btih:xyz", category="radarr") is True

        _, kwargs = qbit.add_urls.call_args
        assert kwargs["category"] == "radarr"
        assert kwargs["savepath"] == "/tank/Downloads/Completed"


def test_add_torrent_file_uploads_bytes():
    with patch.object(torrent_handler, "client") as mock_client:
        qbit = MagicMock()
        qbit.add_torrent_files.return_value = True
        mock_client.return_value = qbit

        assert torrent_handler.add_torrent_file(CFG, b"fake_torrent_bytes", "test.torrent", category="radarr") is True

        args, kwargs = qbit.add_torrent_files.call_args
        assert args[0] == b"fake_torrent_bytes"
        assert args[1] == "test.torrent"
        assert kwargs["category"] == "radarr"


def test_add_torrent_reports_errors_instead_of_raising():
    with patch.object(torrent_handler, "client") as mock_client:
        qbit = MagicMock()
        qbit.add_urls.side_effect = qbittorrent.QBitAuthError("qBittorrent rejected the username or password.")
        mock_client.return_value = qbit

        result = torrent_handler.add_torrent(CFG, "magnet:?xt=urn:btih:xyz")
        assert result["ok"] is False
        assert "username or password" in result["error"]


def test_pause_and_resume_map_onto_the_client():
    with patch.object(torrent_handler, "client") as mock_client:
        qbit = MagicMock()
        qbit.set_torrent_state.return_value = True
        mock_client.return_value = qbit

        assert torrent_handler.pause_torrents(CFG) is True
        assert torrent_handler.resume_torrents(CFG, hashes="abc") is True
        assert qbit.set_torrent_state.call_args_list[0].kwargs == {"hashes": "all"}
        assert qbit.set_torrent_state.call_args_list[1].kwargs == {"hashes": "abc"}
        assert qbit.set_torrent_state.call_args_list[0].args == (False,)
        assert qbit.set_torrent_state.call_args_list[1].args == (True,)


def test_get_torrents_delegates_to_client():
    with patch.object(torrent_handler, "client") as mock_client:
        qbit = MagicMock()
        qbit.torrents_info.return_value = [{"name": "one"}]
        mock_client.return_value = qbit

        assert torrent_handler.get_torrents(CFG, filter_mode="downloading") == [{"name": "one"}]
        qbit.torrents_info.assert_called_once_with(status_filter="downloading")


def test_qbit_session_returns_the_clients_session():
    with patch("requests.Session") as session_cls, \
            patch.object(qbittorrent.QBittorrentClient, "login", return_value=True):
        session = MagicMock()
        session_cls.return_value = session
        assert torrent_handler.qbit_session(CFG) is session


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


def test_format_torrents_status_survives_junk_values():
    out = torrent_handler.format_torrents_status(
        [{"name": None, "progress": "not-a-number", "size": None, "state": "stoppedDL"}]
    )
    assert "0.0%" in out
    assert "stoppedDL" in out


def test_format_torrents_status_empty():
    assert "No active torrents" in torrent_handler.format_torrents_status([], active_only=True)
    assert "No torrents found" in torrent_handler.format_torrents_status([])
