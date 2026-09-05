```text
  ___  ____  _   _ ____  ____   ___ _____ ____
 / _ \|  _ \| | | / ___|| __ ) / _ \_   _/ ___|
| | | | |_) | | | \___ \|  _ \| | | || | \___ \
| |_| |  __/| |_| |___) | |_) | |_| || |  ___) |
 \___/|_|    \___/|____/|_____/ \___/ |_| |____/
```

# OpusBots

Self-hosted, unified Telegram bot for homelab media automation, torrent management, video downloads, and music organization.

OpusBots consolidates all homelab media tasks into **one single, powerful Telegram bot** backed by a lightweight web administration panel. Manage your entire media pipeline — torrents, movies, audio tracks, playlists, and disk storage — directly from a single Telegram conversation.

No hardcoded secrets. No juggling 3 separate bot tokens or chat windows. Zero duplicate logic.

---

## Unified Architecture

```text
                               Telegram User
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │   OpusBot (Single)  │
                          └──────────┬──────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
         ▼                           ▼                           ▼
  🧲 Torrents                  🎬 Movies                   🎵 Music
  (qBittorrent)               (yt-dlp Video)             (yt-dlp Audio)
         │                           │                           │
  Auto Category:             Resolution Picker:          MP3 320k / FLAC
  Sonarr / Radarr            1080p / 720p / Best         Embedded Artwork
         │                           │                   Background Queue
         ▼                           ▼                           ▼
  /tank/Downloads             /tank/Movies                 /tank/Music
  
                                     ▲
                                     │
                         ┌──────────────────────┐
                         │   Config Web Panel   │
                         │    (Port 8090)       │
                         └──────────┬───────────┘
                                    │
                                    ▼
                               config.json
```

---

## Key Features & Improvements

- **Single Telegram Bot**: One bot token, one chat interface for all media workflows.
- **Smart Link & Media Detection**:
  - **Magnet link / .torrent URL**: Automatically sent to qBittorrent with smart category detection (`radarr` vs `tv-sonarr`).
  - **.torrent file upload**: Direct upload into chat adds the torrent straight to qBittorrent.
  - **YouTube / Video URL**: Interactive inline keyboard asks if you want **Audio (MP3)**, **Audio (FLAC)**, **Video (Pick Quality)**, or **Full Playlist**.
  - **Video file upload**: Saved straight into your Movies library.
  - **Audio file upload**: Saved straight into your Music library.
- **qBittorrent Integration**:
  - Magnet links, HTTP torrents, and uploaded `.torrent` files.
  - Auto-routing between Radarr and Sonarr categories.
  - Live torrent progress, download speeds, and ETA.
  - Pause, resume, and manage torrents with 1 tap.
- **Movies & Video Downloader**:
  - Resolution picker (`1080p`, `720p`, `480p`, `Best Available`).
  - Non-blocking background downloads with collision protection.
- **Music & Playlist Automation**:
  - High-quality 320kbps MP3 and lossless FLAC output.
  - Automatic high-resolution album artwork embedding.
  - Automatic ID3 metadata tagging (Artist, Album, Title).
  - YouTube playlist downloader with track-by-track and overall progress bars.
  - Dedicated background queue worker so requests never drop or conflict.
  - Direct search with `/search <artist - song>`.
- **Unified Real-time Dashboard (`/status`)**:
  - Disk storage bar charts for Downloads, Movies, and Music paths.
  - Active qBittorrent torrents with download speeds, progress %, and ETA.
  - Active video tasks and elapsed rendering times.
  - Background music queue status and currently playing job.
  - Interactive buttons: `[🔄 Refresh]` `[⏸️ Pause Torrents]` `[▶️ Resume Torrents]` `[📜 Torrents]`.
- **Web Administration Panel**:
  - Live configuration reloading (~10-15s polling without container restarts).
  - Built-in **"Test Bot Token"** button (validates token with Telegram API).
  - Built-in **"Test Connection"** button (validates qBittorrent login & version).
  - Modern, responsive dark terminal aesthetic.
- **Streamlined Container Footprint**:
  - Reduced from 4 containers down to just 2: `opus-bot` + `config-web`.

---

## Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` or `/help` | Interactive welcome guide and navigation menus |
| `/status` or `/dashboard` | Real-time dashboard (storage bars, torrents, video, music queue) |
| `/torrents` | View active and recent torrents in qBittorrent |
| `/downloading` | View currently downloading torrents with speed & ETA |
| `/pause` | Pause all torrents in qBittorrent |
| `/resume` | Resume all torrents in qBittorrent |
| `/video <url>` | Fetch available resolutions and download video to Movies |
| `/yt <url>` or `/mp3 <url>` | Download audio as 320kbps MP3 with embedded tags & art |
| `/flac <url>` | Download audio as lossless FLAC with embedded tags & art |
| `/playlist <url>` | Download entire YouTube playlist with progress indicators |
| `/search <query>` | Search YouTube for track and download best match |
| `/paths` | Display configured media directories and storage usage |
| `/ping` | Check bot health and latency |

---

## Directory Layout

```text
opusbots/
├── docker-compose.yml          # Build-from-source compose definition (2 containers)
├── docker-compose.ghcr.yml     # GHCR prebuilt compose definition
├── Dockerfile.bot              # Unified bot container image
│
├── bots/
│   ├── opus_bot.py             # Main unified bot entrypoint & dispatcher
│   ├── torrent_handler.py      # qBittorrent WebAPI, magnet & .torrent upload
│   ├── video_handler.py        # Video downloads, resolution picker, video uploads
│   ├── music_handler.py        # Audio downloads, playlists, queue worker
│   └── status_handler.py       # System dashboard, disk bars, media metrics
│
├── shared/
│   ├── config.py               # Live JSON config manager & schema migration
│   ├── tgbot.py                # Telegram API wrapper, long polling & HTML parser
│   └── utils.py                # Formatting (size, speed, ETA, progress bars)
│
├── config-web/
│   ├── app.py                  # Flask web administration & API
│   ├── Dockerfile              # Web panel container image
│   ├── requirements.txt
│   └── templates/
│       ├── config.html         # Terminal configuration UI with AJAX test buttons
│       └── login.html          # Authentication page
│
├── tests/                      # Automated test suite (pytest)
├── .env.example
└── requirements-bot.txt
```

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/lucif3r-d3vil/opusbots.git
cd opusbots
```

### 2. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Generate a secure secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Edit `.env`:

```env
ADMIN_USER=admin
ADMIN_PASS=change-me-to-something-strong
FLASK_SECRET_KEY=your-generated-64-character-hex-string
MEDIA_ROOT=/tank
```

### 3. Start the Stack

```bash
docker compose up -d --build
```

### 4. Configure via Web Panel

Open your browser at:

```text
http://<server-ip>:8090
```

Log in with your `ADMIN_USER` and `ADMIN_PASS`. Configure:
- **Telegram Bot Token**: Created via [@BotFather](https://t.me/BotFather) on Telegram.
- **Allowed Telegram User ID**: Your Telegram numerical user ID (e.g. from [@userinfobot](https://t.me/userinfobot)).
- **qBittorrent Host, Username & Password**: Your qBittorrent Web UI credentials.
- **Media Paths**: Storage directories under `/tank`.

Click **"Save Configuration"**. OpusBot detects configuration changes automatically within 10–15 seconds without requiring a container restart.

---

## Deploy with Prebuilt GHCR Images

To deploy using prebuilt GitHub Container Registry (GHCR) images in Portainer, Dockge, or TrueNAS:

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

Set these environment variables in your stack manager:
- `GHCR_OWNER`: GitHub username (e.g. `lucif3r-d3vil`)
- `ADMIN_PASS`: Web administration password
- `FLASK_SECRET_KEY`: Random 64-char hex key
- `MEDIA_ROOT`: Path to storage folder (default: `/tank`)

---

## Recommended Media Storage Layout

```text
/tank
├── Downloads
│   └── Completed        <-- qBittorrent save path (auto-sorted by Sonarr/Radarr)
├── Movies               <-- Movie bot saves video downloads & uploads here
└── Music                <-- Music bot organizes by Artist/Album/Title here
```

Typical automation flow:

```text
Telegram (/yt or /playlist) ──► OpusBot ──► /tank/Music ──► Navidrome / Plex / Jellyfin
Magnet / .torrent Upload   ──► OpusBot ──► qBittorrent ──► Sonarr / Radarr ──► /tank/Media
```

---

## Migration from Legacy 3-Bot Setup

If you previously used the older OpusBots 3-bot layout:
- **Automatic Migration**: OpusBot and the Web Config automatically migrate existing configuration files. If your `config.json` contained `mirror_bot_token`, `downloads_bot_token`, or `music_bot_token`, the first available token is seamlessly adopted as `bot_token`.
- **One Chat for Everything**: You only need to message one bot in Telegram to access torrents, video downloads, and music queues.

---

## Running Automated Tests

Run the included pytest suite:

```bash
pytest -v
```

---

## Security Notes

- **Keep Port 8090 Private**: The web configuration panel should be kept on your local LAN or protected behind Cloudflare Access / Tailscale.
- **Restricted Telegram Access**: Always set your `allowed_user_id` so only your Telegram account can command the bot.
- **Docker Socket**: The `/var/run/docker.sock` volume is mounted into `config-web` solely to allow the web panel to restart bot containers.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
