"""
Utility functions for formatting, progress tracking, HTML escaping, and disk stats.
"""

import html
import os
import re


def escape_html(text):
    """Safely escape text for Telegram HTML parse mode."""
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


def progress_bar(percent, width=10, filled_char="█", empty_char="░"):
    """Render a text progress bar: e.g. [██████░░░░] 60.0%"""
    try:
        pct = max(0.0, min(100.0, float(percent)))
    except (ValueError, TypeError):
        pct = 0.0
    filled = int(round(width * pct / 100.0))
    filled = max(0, min(width, filled))
    return filled_char * filled + empty_char * (width - filled)


def format_size(num_bytes):
    """Format byte count into human-readable string (e.g., 1.25 GB)."""
    try:
        n = float(num_bytes)
    except (ValueError, TypeError):
        return "0 B"

    if n < 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if n < 1024.0 or unit == "PB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


def format_speed(bytes_per_sec):
    """Format bytes per second into human-readable speed (e.g., 4.50 MB/s)."""
    try:
        bps = float(bytes_per_sec)
    except (ValueError, TypeError):
        return "0 B/s"
    return f"{format_size(bps)}/s"


def format_eta(seconds):
    """Format seconds into readable ETA string (e.g., '1h 24m' or '45s')."""
    try:
        s = int(seconds)
    except (ValueError, TypeError):
        return "unknown"

    if s <= 0:
        return "0s"
    if s >= 8640000:  # ~100 days
        return "unknown"

    days, remainder = divmod(s, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def sanitize_filename(name, max_len=80, default="file"):
    """Sanitize string for safe filesystem usage."""
    if not name:
        return default
    # Remove unsafe characters
    clean = re.sub(r'[^\w\s\-\.]', '', str(name)).strip()
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean[:max_len].strip()
    return clean or default


def get_disk_usage(path):
    """
    Get disk statistics for a given path using os.statvfs.
    Returns a dict with free_gb, total_gb, used_gb, used_pct, bar, and available.
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        st = os.statvfs(path)
        total_bytes = st.f_blocks * st.f_frsize
        free_bytes = st.f_bavail * st.f_frsize
        used_bytes = total_bytes - free_bytes
        total_gb = total_bytes / (1024 ** 3)
        free_gb = free_bytes / (1024 ** 3)
        used_gb = used_bytes / (1024 ** 3)
        used_pct = (used_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0

        bar = progress_bar(used_pct, width=10)

        return {
            "available": True,
            "path": path,
            "total_gb": round(total_gb, 2),
            "free_gb": round(free_gb, 2),
            "used_gb": round(used_gb, 2),
            "used_pct": round(used_pct, 1),
            "bar": bar,
        }
    except Exception as e:
        return {
            "available": False,
            "path": path,
            "error": str(e),
            "total_gb": 0.0,
            "free_gb": 0.0,
            "used_gb": 0.0,
            "used_pct": 0.0,
            "bar": progress_bar(0, width=10),
        }
