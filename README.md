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
- **qBittorrent Integration** (Web API v2, works with qBittorrent **4.x and 5.x**):
  - Magnet links, HTTP torrents, and uploaded `.torrent` files.
  - Auto-routing between Radarr and Sonarr categories (with a safe fallback and a
    warning when the category does not exist in qBittorrent yet).
  - Radarr-style **Host + Port** fields: paste `192.168.1.50:30024`, `http://192.168.1.50:30024`,
    `qbit:8080` or `https://qbit.example.com` — the address is normalised for you.
  - One cached, authenticated session instead of a login per API call, so OpusBots can
    never trip qBittorrent's "too many failed attempts" IP ban.
  - Login failures are told apart: wrong password vs. banned IP vs. wrong port vs.
    reverse-proxy/URL-base vs. self-signed TLS vs. `localhost` inside Docker.
  - Live torrent progress, download speeds, and ETA.
  - Pause, resume, and manage torrents with 1 tap (`torrents/stop|start` on 5.x,
    `torrents/pause|resume` on 4.x — detected automatically).
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
  - Built-in **"Test Connection"** button (validates the qBittorrent login, shows the
    normalised URL it dialled, the server version, and an actionable hint on failure).
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
| `/pause` | Pause (stop) all torrents in qBittorrent |
| `/resume` | Resume (start) all torrents in qBittorrent |
| `/qbit` | Diagnose the qBittorrent connection: URL used, version, and the exact failure |
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
│   ├── qbittorrent.py          # qBittorrent Web API client: URL normalisation,
│   │                           #   cached login, ban back-off, 4.x/5.x endpoints
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
│   └── fake_qbittorrent.py     # Standalone fake qBittorrent Web API (dev + tests)
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
- **qBittorrent Host & Port**: exactly what you enter in Radarr/Sonarr (qBittorrent ▸ Tools ▸ Options ▸ Web User Interface).
- **qBittorrent Username & Password**: Your qBittorrent Web UI credentials.
- **Advanced (optional)**: *URL Base* for a reverse-proxied qBittorrent, and *Verify TLS certificate* (untick for self-signed https).
- **Media Paths**: Storage directories under `/tank`.

Click **"Test Connection"** first — it prints the exact URL OpusBots will dial and, when
something is wrong, tells you which knob to turn. Then click **"Save Configuration"**.
OpusBot detects configuration changes automatically within 10–15 seconds without requiring a container restart.

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

Run the included pytest suite (no Docker, no network and no real qBittorrent needed —
the qBittorrent tests run against a fake Web API server in `tests/fake_qbittorrent.py`):

```bash
pip install -r requirements-bot.txt pytest flask docker
pytest -v
```

To poke at the config panel without a qBittorrent install:

```bash
python -m tests.fake_qbittorrent --port 8080          # emulates qBittorrent 5.x
python -m tests.fake_qbittorrent --port 8080 --api-version 2.9.3 --version v4.6.5   # emulates 4.x
python config-web/app.py                              # panel on http://localhost:8090
```

---

## Troubleshooting qBittorrent

Send `/qbit` to the bot, or press **Test Connection** in the web panel. Both report the
normalised URL, the qBittorrent version and a specific hint. The usual suspects:

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| `Could not reach qBittorrent ... connection was refused` | Wrong port, or qBittorrent's Web UI is disabled | Use the port from qBittorrent ▸ Tools ▸ Options ▸ **Web User Interface** (the same one Radarr uses) |
| `Could not reach qBittorrent ... 'localhost'` | Inside Docker, `localhost` is the *bot container*, not your server | Use the LAN IP (`192.168.1.50`), the container/service name (`qbittorrent:8080`) or `host.docker.internal` |
| `... hostname could not be resolved` | DNS name unknown inside the container | Use an IP, or add the name to the container's DNS/network |
| `qBittorrent rejected the username or password` | Wrong credentials | qBittorrent 5.x generates a **random** Web UI password on first start and prints it to its own log |
| `Your IP address has been banned ...` | 5 failed logins → qBittorrent bans the IP for ~1 hour | Wait, or clear it in qBittorrent ▸ Options ▸ Web UI ▸ Security (*Ban duration*), or restart qBittorrent. OpusBots then backs off instead of retrying, so the ban is not extended |
| `HTTP 403 ...` while the browser works fine | qBittorrent host-header validation / domain list | Add the address to the domain list, whitelist the bot's subnet, or set `WebUI\HostHeaderValidation=false` in `qBittorrent.conf` |
| `answered with a web page instead of the qBittorrent API` | Reverse proxy in front of qBittorrent | Set **URL Base** (e.g. `/qbittorrent`) — Radarr's "URL Base" |
| `TLS error while contacting qBittorrent` | Self-signed certificate | Use `http://`, or untick *Verify TLS certificate* |
| `/pause` or `/resume` did nothing | qBittorrent 5.x renamed the endpoints | Fixed: OpusBots uses `torrents/stop|start` on 5.x and falls back to `torrents/pause|resume` on 4.x |
| Torrent added but Radarr/Sonarr ignores it | The category does not exist in qBittorrent | Create the `radarr` / `tv-sonarr` categories in qBittorrent; OpusBots warns you in chat when it had to add a torrent without its category |

---

## Security Notes

- **Keep Port 8090 Private**: The web configuration panel should be kept on your local LAN or protected behind Cloudflare Access / Tailscale.
- **Restricted Telegram Access**: Always set your `allowed_user_id` so only your Telegram account can command the bot.
- **Docker Socket**: The `/var/run/docker.sock` volume is mounted into `config-web` solely to allow the web panel to restart bot containers.
- **Panel Login**: `ADMIN_PASS` and `FLASK_SECRET_KEY` must be changed from their defaults (the panel warns you if they are not). Sign-in is rate limited, session cookies are `HttpOnly`/`SameSite`, and security headers are set on every response. Set `COOKIE_SECURE=1` when serving the panel over HTTPS.
- **Stored Secrets**: `config/config.json` holds the Telegram token and the qBittorrent password in plain text — keep the `config/` volume private (it is git-ignored).
- **Unknown Telegram Users**: are ignored silently; their user ID is written to the `opus-bot` container log so you can copy it into *Allowed Telegram User ID*.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
