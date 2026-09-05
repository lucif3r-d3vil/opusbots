import pytest
from unittest.mock import MagicMock, patch
from shared import tgbot


def test_send_success():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}
        mock_post.return_value = mock_resp

        msg_id = tgbot.send("FAKE_TOKEN", 123456, "Hello world")
        assert msg_id == 42
        mock_post.assert_called_once()


def test_send_html_fallback():
    with patch("requests.post") as mock_post:
        # First call fails on HTML parse error
        fail_resp = MagicMock()
        fail_resp.json.return_value = {"ok": False, "description": "Bad Request: can't parse entities"}
        # Second call succeeds
        ok_resp = MagicMock()
        ok_resp.json.return_value = {"ok": True, "result": {"message_id": 43}}
        mock_post.side_effect = [fail_resp, ok_resp]

        msg_id = tgbot.send("FAKE_TOKEN", 123456, "Unclosed <b> tag", parse_mode="HTML")
        assert msg_id == 43
        assert mock_post.call_count == 2


def test_get_me():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"id": 123, "is_bot": True, "first_name": "Opus", "username": "OpusBot"}
        }
        mock_get.return_value = mock_resp

        ok, res = tgbot.get_me("FAKE_TOKEN")
        assert ok is True
        assert res["username"] == "OpusBot"

    ok, res = tgbot.get_me("")
    assert ok is False


def test_inline_keyboard():
    kb = tgbot.inline_keyboard([
        [{"text": "Btn 1", "callback_data": "1"}, {"text": "Btn 2", "callback_data": "2"}]
    ])
    assert "inline_keyboard" in kb
    assert len(kb["inline_keyboard"][0]) == 2
