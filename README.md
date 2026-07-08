```text
  ___  ____  _   _ ____  ____   ___ _____ ____
 / _ \|  _ \| | | / ___|| __ ) / _ \_   _/ ___|
| | | | |_) | | | \___ \|  _ \| | | || | \___ \
| |_| |  __/| |_| |___) | |_) | |_| || |  ___) |
 \___/|_|    \___/|____/|_____/ \___/ |_| |____/
```

# OpusBots

Self-hosted Telegram bots for media automation, downloads, and homelab workflows.

OpusBots consists of three focused Telegram bots and a lightweight web administration panel. Each bot has a single responsibility, shares a common configuration system, and runs from a single Docker image.

No hardcoded secrets. No duplicated logic. No giant "does everything" bot.

---

## Architecture

```text
                    Telegram

                        │
         ┌──────────────┼──────────────┐
         │              │              │
         ▼              ▼              ▼

    Mirror Bot    Downloads Bot    Music Bot
         │              │              │
         ▼              ▼              ▼

   qBittorrent      Movies Path    Music Path
                                        │
                                        ▼
                                   Background
                                      Queue

                        ▲
                        │
                   Config Web
                        │
                        ▼
                  config.json
```

---

## Features

- Three dedicated Telegram bots
- Single Docker image for all bots
- Live configuration updates
- Web-based administration panel
- qBittorrent integration
- YouTube downloads via yt-dlp
- MP3 and FLAC music downloads
- Playlist support
- Background music download queue
- Docker Compose deployment
- GHCR container publishing
- Portainer and Dockge compatible

---

## Bots

### Mirror Bot

Torrent automation only.

Supported:

- Magnet links
- Torrent links
- qBittorrent integration
- Auto categorization
- Download monitoring

Commands:

```text
/status
/downloading
/pause
/resume
```

---

### Downloads Bot

Movie downloads only.

Supported:

- Telegram video uploads
- YouTube video downloads
- Resolution selection
- Direct save to movies library

Commands:

```text
/status
```

---

### Music Bot

Music downloads only.

Supported:

```text
/yt
/flac
/playlist
/search
```

Features:

- MP3 output
- FLAC output
- Embedded metadata
- Embedded artwork
- Playlist downloads
- Background queue processing
- Automatic folder organization

---

## Directory Layout

```text
docker-compose.yml
docker-compose.ghcr.yml
Dockerfile.bot

bots/
├── mirror_bot.py
├── downloads_bot.py
└── music_bot.py

shared/
├── config.py
└── tgbot.py

config-web/

config/
└── config.json

.env
```

---

## Quick Start

Create the stack:

```bash
git clone https://github.com/lucif3r-d3vil/opusbots.git
cd opusbots

cp .env.example .env
```

Generate a secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Update:

```env
ADMIN_USER=admin
ADMIN_PASS=changeme
FLASK_SECRET_KEY=<generated-secret>
```

Start:

```bash
docker compose up -d --build
```

Open:

```text
http://<server-ip>:8090
```

Login and configure:

- Telegram Bot Tokens
- Telegram User ID
- qBittorrent Credentials
- Media Paths

Bots automatically reload configuration changes.

---

## Media Layout

Recommended:

```text
/tank
├── Downloads
│   └── Completed
├── Movies
├── TV
├── Music
└── Musictemp
```

Typical workflow:

```text
Music Bot
    ↓
/tank/Musictemp
    ↓
Beets
    ↓
/tank/Music
    ↓
Navidrome
```

---

## Deploy with GHCR

Pull prebuilt images:

```bash
docker pull ghcr.io/lucif3r-d3vil/opusbots-bot:latest
docker pull ghcr.io/lucif3r-d3vil/opusbots-config-web:latest
```

Or deploy with:

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

Supported:

- Docker
- Dockge
- Portainer
- Debian
- Ubuntu
- Proxmox
- TrueNAS SCALE

---

## Updating

```bash
docker compose pull
docker compose up -d
```

View logs:

```bash
docker logs -f mirror-bot
docker logs -f downloads-bot
docker logs -f music-bot
docker logs -f config-web
```

---

## Security Notes

The web interface stores:

- Telegram bot tokens
- qBittorrent credentials
- Media paths

The restart functionality requires:

```text
/var/run/docker.sock
```

which grants root-equivalent Docker access.

Recommendations:

- Keep the UI behind Cloudflare Access
- Use Tailscale or a VPN
- Do not expose port 8090 publicly
- Use strong administrator credentials

---

## Adding More Bots

Create a new bot module:

```text
bots/new_bot.py
```

Add configuration defaults:

```text
shared/config.py
```

Add fields to:

```text
config-web/templates/config.html
```

Then create a new service using the same Docker image.

---

## License

MIT
