import pytest
from unittest.mock import MagicMock, patch
from bots import opus_bot


def test_check_auth():
    cfg = {"telegram": {"allowed_user_id": 123456}}

    # Authorized user message
    up_auth = {"message": {"from": {"id": 123456}, "chat": {"id": 123456}}}
    is_auth, uid, cid = opus_bot.check_auth(up_auth, cfg)
    assert is_auth is True
    assert uid == 123456

    # Unauthorized user message
    up_unauth = {"message": {"from": {"id": 999999}, "chat": {"id": 999999}}}
    is_auth, uid, cid = opus_bot.check_auth(up_unauth, cfg)
    assert is_auth is False

    # Open config (0)
    cfg_open = {"telegram": {"allowed_user_id": 0}}
    is_auth, uid, cid = opus_bot.check_auth(up_unauth, cfg_open)
    assert is_auth is True


def test_handle_message_commands(tmp_path):
    cfg = {
        "telegram": {"allowed_user_id": 123456, "bot_token": "FAKE_TOKEN"},
        "paths": {"downloads_completed": str(tmp_path), "movies": str(tmp_path), "music": str(tmp_path)},
        "qbittorrent": {"host": "http://qbit:8080", "user": "admin", "pass": "secret"}
    }

    with patch("shared.tgbot.send") as mock_send:
        # /ping command
        up_ping = {"message": {"from": {"id": 123456}, "chat": {"id": 123456}, "text": "/ping"}}
        opus_bot.handle_message(up_ping, cfg, "FAKE_TOKEN")
        assert mock_send.call_count == 1
        assert "Pong" in mock_send.call_args[0][2]

        # /start command
        up_start = {"message": {"from": {"id": 123456}, "chat": {"id": 123456}, "text": "/start"}}
        opus_bot.handle_message(up_start, cfg, "FAKE_TOKEN")
        assert mock_send.call_count == 2
        assert "OpusBots" in mock_send.call_args[0][2]


def test_handle_magnet_message():
    cfg = {
        "telegram": {"allowed_user_id": 123456, "bot_token": "FAKE_TOKEN"},
        "paths": {"downloads_completed": "/tank/Downloads/Completed"},
        "qbittorrent": {"host": "http://qbit:8080", "user": "admin", "pass": "secret"}
    }

    with patch("bots.torrent_handler.add_magnet") as mock_add, \
         patch("shared.tgbot.send") as mock_send, \
         patch("shared.tgbot.send_chat_action"):

        mock_add.return_value = True

        up_magnet = {
            "message": {
                "from": {"id": 123456},
                "chat": {"id": 123456},
                "text": "magnet:?xt=urn:btih:1234567890abcdef"
            }
        }
        opus_bot.handle_message(up_magnet, cfg, "FAKE_TOKEN")
        mock_add.assert_called_once()
        assert "Added to qBittorrent" in mock_send.call_args[0][2]


def test_handle_youtube_url_prompt():
    cfg = {
        "telegram": {"allowed_user_id": 123456, "bot_token": "FAKE_TOKEN"},
    }

    with patch("shared.tgbot.send") as mock_send:
        up_yt = {
            "message": {
                "from": {"id": 123456},
                "chat": {"id": 123456},
                "text": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            }
        }
        opus_bot.handle_message(up_yt, cfg, "FAKE_TOKEN")
        mock_send.assert_called_once()
        assert "Media Link Detected" in mock_send.call_args[0][2]
        # Check inline keyboard has choices
        kb = mock_send.call_args[1]["reply_markup"]
        assert "inline_keyboard" in kb


def test_handle_callbacks():
    cfg = {
        "telegram": {"allowed_user_id": 123456, "bot_token": "FAKE_TOKEN"},
        "paths": {"downloads_completed": "/tank/Downloads/Completed", "movies": "/tank/Movies", "music": "/tank/Music"},
        "qbittorrent": {"host": "http://qbit:8080", "user": "admin", "pass": "secret"}
    }

    with patch("shared.tgbot.answer_callback") as mock_ans, \
         patch("shared.tgbot.edit_message") as mock_edit, \
         patch("bots.torrent_handler.pause_torrents") as mock_pause, \
         patch("bots.status_handler.build_status_text", return_value="Status Text"):

        # 1. Help navigation
        up_help = {
            "callback_query": {
                "id": "cb1",
                "from": {"id": 123456},
                "message": {"chat": {"id": 123456}, "message_id": 10},
                "data": "help:torrents",
            }
        }
        opus_bot.handle_callback(up_help, cfg, "FAKE_TOKEN")
        mock_ans.assert_called_with("FAKE_TOKEN", "cb1")
        mock_edit.assert_called()
        assert "Torrents & qBittorrent" in mock_edit.call_args[0][3]

        # 2. Pause all torrents
        up_pause = {
            "callback_query": {
                "id": "cb2",
                "from": {"id": 123456},
                "message": {"chat": {"id": 123456}, "message_id": 10},
                "data": "status:pause_all",
            }
        }
        opus_bot.handle_callback(up_pause, cfg, "FAKE_TOKEN")
        mock_pause.assert_called_once()

        # 3. Media Choice MP3
        opus_bot.pending_media_links["link1"] = {"url": "https://youtu.be/123", "timestamp": 9999999999}
        up_mp3 = {
            "callback_query": {
                "id": "cb3",
                "from": {"id": 123456},
                "message": {"chat": {"id": 123456}, "message_id": 10},
                "data": "choice:mp3:link1",
            }
        }
        with patch("bots.music_handler.enqueue_job") as mock_enqueue:
            opus_bot.handle_callback(up_mp3, cfg, "FAKE_TOKEN")
            mock_enqueue.assert_called_once()


def test_handle_media_uploads(tmp_path):
    cfg = {
        "telegram": {"allowed_user_id": 123456, "bot_token": "FAKE_TOKEN"},
        "paths": {"downloads_completed": str(tmp_path), "movies": str(tmp_path), "music": str(tmp_path)},
        "qbittorrent": {"host": "http://qbit:8080", "user": "admin", "pass": "secret"}
    }

    with patch("shared.tgbot.get_file_bytes", return_value=(b"fake_torrent_bytes", "test.torrent")), \
         patch("bots.torrent_handler.add_torrent_file", return_value=True) as mock_add_tf, \
         patch("shared.tgbot.send") as mock_send, \
         patch("shared.tgbot.send_chat_action"):

        # .torrent upload
        msg_torrent = {
            "from": {"id": 123456},
            "chat": {"id": 123456},
            "document": {"file_id": "doc_123", "file_name": "MyMovie.torrent"}
        }
        opus_bot.handle_media_upload(msg_torrent, cfg, "FAKE_TOKEN", 123456)
        mock_add_tf.assert_called_once()
        assert "Torrent File Added" in mock_send.call_args[0][2]
