```text
 ██████╗ ██████╗ ██╗   ██╗███████╗██████╗  ██████╗ ████████╗███████╗
██╔═══██╗██╔══██╗██║   ██║██╔════╝██╔══██╗██╔═══██╗╚══██╔══╝██╔════╝
██║   ██║██████╔╝██║   ██║███████╗██████╔╝██║   ██║   ██║   ███████╗
██║   ██║██╔═══╝ ██║   ██║╚════██║██╔══██╗██║   ██║   ██║   ╚════██║
╚██████╔╝██║     ╚██████╔╝███████║██████╔╝╚██████╔╝   ██║   ███████║
 ╚═════╝ ╚═╝      ╚═════╝ ╚══════╝╚═════╝  ╚═════╝    ╚═╝   ╚══════╝
```

# OpusBots

Self-hosted Telegram bots for homelab automation, media management, downloads, and music workflows.

OpusBots consolidates multiple Telegram bots into a single Docker-powered stack with centralized configuration management through a lightweight web interface. Instead of maintaining separate scripts with hardcoded credentials, all bots share a common framework, a live-editable configuration system, and a single deployment workflow.

---

## Features

- Centralized web-based configuration management
- Single Docker image shared across multiple bots
- Live configuration reloads without restarts
- Built-in yt-dlp and FFmpeg support
- qBittorrent integration
- Telegram-first workflow
- Docker Compose deployment
- GitHub Container Registry (GHCR) support
- Portainer and Dockge compatible
- Designed for homelab environments

---

## Included Services

### Mirror Bot

Handles mirror and download-related Telegram commands.

### Downloads Bot

Integrates with qBittorrent and media workflows.

### Music Bot

Provides music, playlist, and media downloads powered by yt-dlp.

### Config Web

Lightweight Flask administration panel for managing tokens, credentials, paths, and service settings.

---

## Recommended Directory Layout

```text
/opt/docker/opusbots
├── compose.yml
├── .env
└── config
    └── config.json
```

Media storage:

```text
/mnt/tank
├── Movies
├── TV
├── Music
└── Downloads
```

---

## Quick Start

Create the deployment directory:

```bash
mkdir -p /opt/docker/opusbots/config
cd /opt/docker/opusbots
```

Create `.env`:

```env
ADMIN_USER=admin
ADMIN_PASS=ChangeMeToSomethingStrong
FLASK_SECRET_KEY=replace-with-random-secret
```

Generate a Flask secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Save the output into `FLASK_SECRET_KEY`.

Create `compose.yml` using the example below and start the stack:

```bash
docker compose pull
docker compose up -d
```

Open:

```text
http://<server-ip>:8090
```

Login using the credentials from `.env`.

---

## Docker Compose

```yaml
services:
  mirror-bot:
    image: ghcr.io/lucif3r-d3vil/opusbots-bot:latest
    container_name: mirror-bot
    restart: unless-stopped
    command: ["python", "bots/mirror_bot.py"]
    volumes:
      - /opt/docker/opusbots/config:/config
      - /mnt/tank:/mnt/tank
    environment:
      PYTHONUNBUFFERED: "1"

  downloads-bot:
    image: ghcr.io/lucif3r-d3vil/opusbots-bot:latest
    container_name: downloads-bot
    restart: unless-stopped
    command: ["python", "bots/downloads_bot.py"]
    volumes:
      - /opt/docker/opusbots/config:/config
      - /mnt/tank:/mnt/tank
    environment:
      PYTHONUNBUFFERED: "1"

  music-bot:
    image: ghcr.io/lucif3r-d3vil/opusbots-bot:latest
    container_name: music-bot
    restart: unless-stopped
    command: ["python", "bots/music_bot.py"]
    volumes:
      - /opt/docker/opusbots/config:/config
      - /mnt/tank:/mnt/tank
    environment:
      PYTHONUNBUFFERED: "1"

  config-web:
    image: ghcr.io/lucif3r-d3vil/opusbots-config-web:latest
    container_name: config-web
    restart: unless-stopped

    ports:
      - "8090:8090"

    volumes:
      - /opt/docker/opusbots/config:/config
      - /var/run/docker.sock:/var/run/docker.sock

    environment:
      ADMIN_USER: ${ADMIN_USER}
      ADMIN_PASS: ${ADMIN_PASS}
      FLASK_SECRET_KEY: ${FLASK_SECRET_KEY}
```

---

## Container Images

Latest Config UI:

```bash
docker pull ghcr.io/lucif3r-d3vil/opusbots-config-web:latest
```

Latest Bot Image:

```bash
docker pull ghcr.io/lucif3r-d3vil/opusbots-bot:latest
```

Specific Build:

```bash
docker pull ghcr.io/lucif3r-d3vil/opusbots-config-web:sha-39a12f7
docker pull ghcr.io/lucif3r-d3vil/opusbots-bot:sha-39a12f7
```

---

## Updating

Pull the latest images and recreate containers:

```bash
docker compose pull
docker compose up -d
```

View logs:

```bash
docker logs -f config-web
docker logs -f mirror-bot
docker logs -f downloads-bot
docker logs -f music-bot
```

Check running containers:

```bash
docker ps
```

---

## Security Notes

The configuration panel stores:

- Telegram bot tokens
- qBittorrent credentials
- Media paths

The Config Web container mounts Docker's socket:

```text
/var/run/docker.sock
```

This grants root-equivalent access to the Docker host and is required for the built-in Restart buttons.

Recommendations:

- Keep the UI behind Cloudflare Access, Tailscale, or a reverse proxy with authentication
- Do not expose port 8090 directly to the public internet
- Use a strong administrator password
- Keep your `.env` file private

---

## Homelab Friendly

Works well with:

- Docker
- Dockge
- Portainer
- Debian
- Ubuntu
- TrueNAS SCALE
- Proxmox Docker Hosts

---

## License

MIT
