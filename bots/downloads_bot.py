"""
Legacy Downloads Bot entrypoint - redirected to unified OpusBot.
All torrent mirroring, movie downloads, and music workflows are now handled
by a single bot in bots/opus_bot.py.
"""

from bots.opus_bot import main

if __name__ == "__main__":
    print("[OpusBots] Note: All bots are now unified into 1 bot (bots/opus_bot.py).")
    main()
