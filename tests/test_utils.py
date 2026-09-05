import os
import pytest
from shared import utils


def test_escape_html():
    assert utils.escape_html("Hello <World> & 'Friends'") == "Hello &lt;World&gt; &amp; 'Friends'"
    assert utils.escape_html(None) == ""
    assert utils.escape_html(123) == "123"


def test_progress_bar():
    bar_0 = utils.progress_bar(0)
    assert bar_0 == "░░░░░░░░░░"

    bar_50 = utils.progress_bar(50)
    assert bar_50 == "█████░░░░░"

    bar_100 = utils.progress_bar(100)
    assert bar_100 == "██████████"

    # Edge cases
    assert utils.progress_bar(-10) == "░░░░░░░░░░"
    assert utils.progress_bar(150) == "██████████"
    assert utils.progress_bar("invalid") == "░░░░░░░░░░"


def test_format_size():
    assert utils.format_size(500) == "500 B"
    assert utils.format_size(1024) == "1.00 KB"
    assert utils.format_size(1024 * 1024 * 5.5) == "5.50 MB"
    assert utils.format_size(1024 * 1024 * 1024 * 2.25) == "2.25 GB"
    assert utils.format_size(-50) == "0 B"
    assert utils.format_size("invalid") == "0 B"


def test_format_speed():
    assert utils.format_speed(1024 * 1024 * 3.5) == "3.50 MB/s"
    assert utils.format_speed("invalid") == "0 B/s"


def test_format_eta():
    assert utils.format_eta(30) == "30s"
    assert utils.format_eta(90) == "1m 30s"
    assert utils.format_eta(3665) == "1h 1m"
    assert utils.format_eta(86400 * 2 + 3600 * 3 + 120) == "2d 3h 2m"
    assert utils.format_eta(0) == "0s"
    assert utils.format_eta(9000000) == "unknown"
    assert utils.format_eta("invalid") == "unknown"


def test_sanitize_filename():
    assert utils.sanitize_filename("Movie: Title / Episode * 1?") == "Movie Title Episode 1"
    assert utils.sanitize_filename("   ") == "file"
    assert utils.sanitize_filename(None) == "file"


def test_get_disk_usage(tmp_path):
    stats = utils.get_disk_usage(str(tmp_path))
    assert stats["available"] is True
    assert stats["total_gb"] > 0
    assert stats["free_gb"] > 0
    assert 0 <= stats["used_pct"] <= 100
    assert len(stats["bar"]) == 10
