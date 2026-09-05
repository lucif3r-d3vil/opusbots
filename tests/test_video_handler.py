import json
import os
import pytest
from unittest.mock import MagicMock, patch
from bots import video_handler


def test_is_youtube_url():
    assert video_handler.is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert video_handler.is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert video_handler.is_youtube_url("https://youtube.com/shorts/dQw4w9WgXcQ")
    assert not video_handler.is_youtube_url("https://example.com/movie.mp4")


def test_is_video_url():
    assert video_handler.is_video_url("https://example.com/movie.mp4")
    assert video_handler.is_video_url("https://youtube.com/watch?v=12345678901")
    assert not video_handler.is_video_url("hello world")


def test_get_video_formats():
    fake_info = {
        "title": "Amazing 4K Video",
        "duration_string": "10:00",
        "formats": [
            {"format_id": "137", "vcodec": "avc1", "height": 1080, "ext": "mp4", "filesize": 100 * 1024 * 1024},
            {"format_id": "136", "vcodec": "avc1", "height": 720, "ext": "mp4", "filesize": 50 * 1024 * 1024},
            {"format_id": "audio", "vcodec": "none", "height": None, "ext": "m4a"},
        ]
    }

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(fake_info)
        mock_run.return_value = mock_proc

        title, title_safe, fmts, duration = video_handler.get_video_formats("https://youtu.be/12345678901")
        assert title == "Amazing 4K Video"
        assert title_safe == "Amazing 4K Video"
        assert duration == "10:00"
        assert len(fmts) == 2
        assert fmts[0]["res"] == "1080p"
        assert fmts[1]["res"] == "720p"


def test_build_resolution_keyboard():
    formats = [
        {"res": "1080p", "size": "100 MB"},
        {"res": "720p", "size": "50 MB"},
    ]
    kb = video_handler.build_resolution_keyboard(formats, "q123")
    assert "inline_keyboard" in kb
    # Check that cancel button is included
    assert any("Cancel" in btn["text"] for row in kb["inline_keyboard"] for btn in row)


def test_handle_uploaded_video(tmp_path):
    movies_dir = str(tmp_path / "Movies")
    cfg = {"paths": {"movies": movies_dir}}

    with patch("shared.tgbot.send_chat_action"), \
         patch("shared.tgbot.send") as mock_send, \
         patch("shared.tgbot.edit_message") as mock_edit, \
         patch("shared.tgbot.download_file") as mock_dl:

        fake_source = tmp_path / "temp_video.mp4"
        fake_source.write_bytes(b"fake_video_content")
        mock_dl.return_value = (str(fake_source), "temp_video.mp4")
        mock_send.return_value = 101

        video_handler.handle_uploaded_video("FAKE_TOKEN", cfg, 123456, "file_id_xyz", "MyMovie.mp4")

        saved_file = os.path.join(movies_dir, "MyMovie.mp4")
        assert os.path.exists(saved_file)
        assert open(saved_file, "rb").read() == b"fake_video_content"
        mock_edit.assert_called_once()
