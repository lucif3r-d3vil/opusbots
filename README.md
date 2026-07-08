```
  ___  ____  _   _ ____  ____   ___ _____ ____
 / _ \|  _ \| | | / ___|| __ ) / _ \_   _/ ___|
| | | | |_) | | | \___ \|  _ \| | | || | \___ \
| |_| |  __/| |_| |___) | |_) | |_| || |  ___) |
 \___/|_|    \___/|____/|____/ \___/ |_| |____/
```

Three single-purpose Telegram bots for a homelab, sharing one Docker image
and one live-editable config, managed from a small web UI instead of
hardcoded values in each script.

  mirror-bot     torrents only        magnet/torrent link -> qBittorrent
  downloads-bot  movies only          video upload or YouTube link -> movies path
  music-bot      music only           YouTube link/search -> MP3/FLAC -> music path

Each bot has exactly one job. Nothing is duplicated between them.


## Layout

```
docker-compose.yml        build-from-source compose (3 bots + config-web)
docker-compose.ghcr.yml   deploy-only compose, pulls prebuilt GHCR images
Dockerfile.bot             single image (python + yt-dlp + ffmpeg baked in)
shared/config.py           config.json read/write, shared by bots + web UI
shared/tgbot.py            Telegram API helpers + generic long-poll loop
bots/mirror_bot.py         torrents -> qBittorrent
bots/downloads_bot.py      movies only (video upload / YouTube download)
bots/music_bot.py          music only (YouTube -> MP3/FLAC, search, playlists)
config-web/                 Flask admin page (login + settings form + restart)
config/config.json          generated on first run -- your live settings live here
.env                        config-web login credentials (copy from .env.example)
```


## First-time setup

1. `cp .env.example .env` and fill in ADMIN_USER, ADMIN_PASS, a random
   FLASK_SECRET_KEY, and optionally MEDIA_ROOT (the host folder holding your
   Movies/Music/Downloads -- defaults to /tank if not set).
2. `docker compose up -d --build`
3. Open `http://<server-ip>:8090`, log in, and fill in:
   - the three Telegram bot tokens (from @BotFather -- three separate bots,
     same as before)
   - your allowed Telegram user ID
   - qBittorrent host/user/password
   - the three media paths (torrent downloads, movies, music)
4. Click "save changes". The bots poll config/config.json roughly every
   15 seconds, so they pick up new values on their own -- no restart needed
   for normal edits. The restart buttons are for edge cases like a hung
   process or an image rebuild.

Put config-web behind your existing Cloudflare Access policy (or just don't
expose port 8090 publicly) -- it holds your qBittorrent password and
Telegram tokens, and its restart buttons work by mounting
/var/run/docker.sock, which is effectively root-equivalent access to the
host. Treat it like any other admin panel with docker.sock access (same
tier as Portainer).


## What each bot does (and does not do)

mirror-bot
  - send a magnet/torrent link -> added to qBittorrent
  - auto-categorizes as movie or TV based on filename (season/episode
    keywords) for Sonarr/Radarr to pick up from qBittorrent's completed
    folder -- that sorting happens outside these bots entirely
  - /status, /downloading, /pause, /resume

downloads-bot (movies only)
  - upload a video file -> saved straight to the movies path
  - paste a YouTube link -> pick a resolution -> saved straight to the
    movies path
  - no audio handling at all, no folder picker (there's only one
    destination now), no TV handling
  - /status shows active downloads, movies disk space, and recent history

music-bot (music only)
  - /yt URL, /flac URL, /playlist URL, /search "artist - song", or just
    paste a link
  - MP3 or FLAC, embedded thumbnail/metadata, organized by
    uploader/album/title
  - a real background queue: requests made while something is already
    downloading now actually run once the current one finishes, instead
    of silently piling up (this was broken in the original script)


## Publishing to GHCR (GitHub Container Registry)

This lets anyone deploy via Portainer/Dockge by pasting a compose file --
no git clone, no build step on the target machine.

1. Push the code to GitHub:

   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<you>/opusbots.git
   git push -u origin main

   .env and config/config.json are already in .gitignore -- secrets never
   get committed.

2. .github/workflows/docker-publish.yml is already in the repo. On push to
   main it builds and pushes:
     ghcr.io/<you>/opusbots-bot:latest
     ghcr.io/<you>/opusbots-config-web:latest
   Also tagged by branch, git SHA, and semver on a v1.2.3-style tag. No
   setup needed -- it uses the repo's built-in GITHUB_TOKEN. Watch it run
   under the repo's Actions tab.

3. Optional: make the packages public so anyone can pull without logging
   in. Go to github.com/<you>?tab=packages, open opusbots-bot -> package
   settings -> change visibility -> public. Repeat for
   opusbots-config-web. Otherwise, `docker login ghcr.io` with a PAT
   (read:packages scope) on the deploy machine.

4. Deploy with docker-compose.ghcr.yml (no build blocks, only image
   references):

   Portainer:
     - Stacks -> Add stack
     - Repository (paste your repo URL, compose path
       docker-compose.ghcr.yml) or Web editor (paste the file directly)
     - Environment variables: GHCR_OWNER, MEDIA_ROOT, ADMIN_USER,
       ADMIN_PASS, FLASK_SECRET_KEY, optionally IMAGE_TAG
     - Deploy, then configure via the web UI on port 8090

   Dockge:
     - + Compose -> paste docker-compose.ghcr.yml
     - fill in the same variables in Dockge's per-stack .env editor
     - deploy, then configure via the web UI on port 8090

Updating later: push to main -> Actions rebuilds :latest -> on the deploy
box:

   docker compose -f docker-compose.ghcr.yml pull
   docker compose -f docker-compose.ghcr.yml up -d

Portainer's "re-pull and redeploy" and Dockge's pull+restart buttons do
the same thing.


## On lossless music (SpotiFLAC, etc.)

Some third-party "get Spotify tracks in FLAC" tools work by pulling the
actual audio stream from paid services (Tidal/Qobuz/Amazon/Deezer) through
unofficial API mirrors, without an account -- that's routing around those
services' subscription and access controls, not a legitimate download
path, so it isn't wired into this project. yt-dlp against YouTube is used
instead, with a real ceiling: YouTube only ever serves lossy AAC, so true
FLAC from YouTube isn't possible either way. For genuinely lossless files,
rip discs you own, buy from Bandcamp, or use your own paid streaming app's
official offline download.


## Known limitation carried over from earlier

None currently -- the music bot's queue-draining bug from the original
scripts has been fixed (see "music-bot" above).


## Adding a fourth bot later

Copy one of the bots/*.py files as a template, add its token key to
DEFAULT_CONFIG in shared/config.py (and to the web form in
config-web/templates/config.html), then add a new service block to both
compose files using the same Dockerfile.bot image with a different
command.
