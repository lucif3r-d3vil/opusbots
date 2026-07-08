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

* Centralized web-based configuration management
* Single Docker image shared across multiple bots
* Live configuration reloads without restarts
* Built-in yt-dlp and FFmpeg support
* qBittorrent integration
* Telegram-first workflow
* Docker Compose deployment
* GitHub Container Registry (GHCR) publishing
* Portainer and Dockge compatible
* Designed for homelab environments

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

## Quick Install

Pull the latest image:

```bash
docker pull ghcr.io/lucif3r-d3vil/opusbots-config-web:latest
```

Run the configuration interface:

```bash
docker run -d \
  --name opusbots-config-web \
  -p 8090:8090 \
  --restart unless-stopped \
  ghcr.io/lucif3r-d3vil/opusbots-config-web:latest
```

Pull a specific build:

```bash
docker pull ghcr.io/lucif3r-d3vil/opusbots-config-web:sha-db47b15
```

---

## Docker Compose

```yaml
services:
  opusbots-config-web:
    image: ghcr.io/lucif3r-d3vil/opusbots-config-web:latest
    container_name: opusbots-config-web
    restart: unless-stopped
    ports:
      - "8090:8090"
```

Deploy:

```bash
docker compose up -d
```

---

## First-Time Setup

1. Copy `.env.example` to `.env`
2. Configure:

   * ADMIN_USER
   * ADMIN_PASS
   * FLASK_SECRET_KEY
3. Start the stack
4. Open:

```text
http://<server-ip>:8090
```

5. Configure:

   * Telegram bot tokens
   * Allowed Telegram user ID
   * qBittorrent credentials
   * Media paths

Bots automatically reload configuration changes without requiring container restarts.

---

## Architecture

```text
┌─────────────────┐
│   Config Web    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  config.json    │
└──────┬─────┬────┘
       │     │
       │     │
       ▼     ▼
┌─────────┐ ┌─────────┐
│ Mirror  │ │Downloads│
│   Bot   │ │   Bot   │
└────┬────┘ └────┬────┘
     │           │
     └─────┬─────┘
           ▼
      ┌────────┐
      │ Music  │
      │  Bot   │
      └────────┘
```

---

## Updating

Pull the latest images:

```bash
docker compose pull
docker compose up -d
```

Or pull a specific build:

```bash
docker pull ghcr.io/lucif3r-d3vil/opusbots-config-web:sha-db47b15
```

---

## Homelab Friendly

Works well with:

* Docker
* Dockge
* Portainer
* Debian
* Ubuntu
* TrueNAS SCALE
* Proxmox Docker Hosts

---

## Security Notice

The configuration panel stores Telegram bot tokens and qBittorrent credentials.

If exposing the interface externally:

* Use Cloudflare Access or equivalent authentication
* Avoid exposing port 8090 directly to the internet
* Treat Docker socket access as root-equivalent access

---

## License

MIT
