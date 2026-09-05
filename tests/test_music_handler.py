import pytest
from unittest.mock import MagicMock, patch
from bots import music_handler


def test_parse_progress():
    line = "[download]  45.2% of ~  12.50MiB at    2.50MiB/s ETA 00:03"
    p = music_handler.parse_progress(line)
    assert p is not None
    assert p["percent"] == 45.2
    assert "12.50MiB" in p["size"]
    assert "2.50MiB/s" in p["speed"]
    assert "00:03" in p["eta"]

    assert music_handler.parse_progress("random log message") is None


def test_get_music_status():
    status = music_handler.get_music_status()
    assert "is_downloading" in status
    assert "queue_size" in status
    assert "active_job" in status


def test_enqueue_job():
    executed = []
    job = lambda: executed.append(True)

    with patch("shared.tgbot.send"):
        music_handler.enqueue_job("FAKE_TOKEN", 123456, job, label="Test Job")

    # Queue worker should pick it up and run it
    import time
    time.sleep(0.1)
    assert len(executed) == 1
