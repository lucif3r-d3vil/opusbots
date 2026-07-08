# HomeLab Telegram Bots

Consolidated Mirror / Downloads / Music bots, sharing one Docker image and one
live-editable config, managed from a small web UI instead of hardcoded values
in each script.

## Layout

```
docker-compose.yml       4 services: mirror-bot, downloads-bot, music-bot, config-web
Dockerfile.bot            single image (python + yt-dlp + ffmpeg baked in) used by all 3 bots
shared/config.py          config.json read/write, shared by bots + web UI
shared/tgbot.py           Telegram API helpers + generic long-poll loop
bots/*.py                 the three bots, now config-driven
config-web/                Flask admin page (login + settings form + restart buttons)
config/config.json         generated on first run — your live settings live here
.env                       config-web login credentials (copy from .env.example)
```

## First-time setup

1. `cp .env.example .env` and fill in `ADMIN_USER`, `ADMIN_PASS`, and a random
   `FLASK_SECRET_KEY` (the file tells you how to generate one).
2. Adjust the `/mnt/tank:/mnt/tank` volume line in `docker-compose.yml` if your
   media pool lives somewhere else.
3. `docker compose up -d --build`
4. Open `http://<server-ip>:8090`, log in, and fill in:
   - The three Telegram bot tokens (from @BotFather — these are three separate
     bots, same as before)
   - Your allowed Telegram user ID
   - qBittorrent host/user/password
   - The four media paths
5. Click **Save changes**. The bots poll `config/config.json` roughly every
   15 seconds, so they'll pick the new values up on their own — no restart
   needed for normal edits. The **Restart** buttons are there for cases like
   a hung process or an image rebuild.

Put `config-web` behind your existing Cloudflare Access policy (or just don't
expose port 8090 publicly) — it holds your qBittorrent password and Telegram
tokens, and its **Restart** buttons work by mounting `/var/run/docker.sock`,
which is effectively root-equivalent access to the host. Treat it like any
other admin panel with docker.sock access (same tier as Portainer).

## What changed vs. the original three scripts

- **No more hardcoded secrets.** Tokens, qBittorrent creds, and paths all
  live in `config/config.json`, edited via the web UI.
- **One image, not three.** `yt-dlp` and `ffmpeg` are baked into
  `Dockerfile.bot` at build time instead of being `apt-get`/`pip install`-ed
  on every container start — faster restarts, and it won't silently break if
  a package mirror is flaky at boot.
- **Shared Telegram helper module** (`shared/tgbot.py`) instead of each bot
  reimplementing `send()`/`edit()`/the polling loop.
- **Live config reload**: change a token or a path in the web UI and the
  relevant bot picks it up within ~15 seconds without a restart.
- Bot logic itself (magnet handling, YouTube resolution picker, folder
  routing, playlist/search downloads) is unchanged — same commands, same
  behavior.

## Known pre-existing limitation carried over

In the music bot, if you send `/yt`, `/flac`, `/playlist`, or `/search` while
something is already downloading, the request gets appended to
`download_queue` — but nothing currently pops items off that queue and runs
them after the active download finishes (this was true in the original
script too). Practically: back-to-back requests only ever run the first one.
If you want, I can wire up an actual queue worker — happy to do that as a
follow-up.

## Publishing to GHCR (GitHub Container Registry)

This turns the project into something you (or anyone) can deploy in
Portainer or Dockge by pasting a compose file — no `git clone`, no build
step on the target machine.

### 1. Push the code to GitHub

```bash
cd telegram-bots
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/telegram-bots.git
git push -u origin main
```

`.env` and `config/config.json` are already in `.gitignore` — your secrets
never get committed.

### 2. Let the included workflow build and push the images

`.github/workflows/docker-publish.yml` is already in the repo. On the first
push to `main` it will:
- Build `Dockerfile.bot` → `ghcr.io/<you>/telegram-bots-bot:latest`
- Build `config-web/Dockerfile` → `ghcr.io/<you>/telegram-bots-config-web:latest`
- Also tag by branch name, git SHA, and (if you push a `v1.2.3` tag) semver

No setup needed — it authenticates using the repo's built-in
`GITHUB_TOKEN`, which already has permission to push to your own GHCR
namespace. Watch it run under the repo's **Actions** tab.

### 3. Make the packages public (optional, one-time)

By default GHCR packages are private, so pulling them would need a login.
To let anyone (including yourself on the homelab box, without auth) pull
them:

1. Go to `https://github.com/<your-username>?tab=packages`
2. Open `telegram-bots-bot` → **Package settings** → **Change visibility** → Public
3. Repeat for `telegram-bots-config-web`

If you'd rather keep them private, `docker login ghcr.io` on the deploy
machine with a GitHub Personal Access Token (`read:packages` scope) instead.

### 4. Deploy with the prebuilt images

Use `docker-compose.ghcr.yml` instead of `docker-compose.yml` — it has no
`build:` blocks, only `image:` references, so Portainer/Dockge never need
to see your source code, just pull and run.

**Portainer:**
1. **Stacks** → **Add stack**
2. Either:
   - **Repository**: paste your GitHub repo URL, set "Compose path" to
     `docker-compose.ghcr.yml`, or
   - **Web editor**: paste the contents of `docker-compose.ghcr.yml` directly
3. Under **Environment variables**, add:
   - `GHCR_OWNER` = your GitHub username (lowercase)
   - `ADMIN_USER`, `ADMIN_PASS`
   - `FLASK_SECRET_KEY` (generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`)
   - `IMAGE_TAG` (optional, defaults to `latest`)
4. Deploy the stack. Portainer creates a `./config` folder next to the
   stack automatically for the bind mount.
5. Before it'll actually respond on Telegram, open the config-web UI
   (port 8090) and fill in bot tokens / qBittorrent creds / media paths,
   same as before.

**Dockge:**
1. **+ Compose** → give it a stack name
2. Paste the contents of `docker-compose.ghcr.yml` into the editor
3. Dockge has a built-in `.env` editor per-stack — add the same variables
   listed above there
4. Deploy, then configure via the web UI on port 8090

### Updating later

Push new commits to `main` → Actions rebuilds and re-pushes `:latest` →
on the homelab box (or in Portainer/Dockge) re-pull and recreate:

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

Portainer has a "Re-pull and redeploy" option on the stack page that does
the same thing; Dockge has a similar "Pull" + "Restart" pair of buttons.

## Adding a fourth bot later


Copy one of the `bots/*.py` files as a template, add its token key to
`DEFAULT_CONFIG` in `shared/config.py` (and to the web form in
`config-web/templates/config.html`), then add a new service block to
`docker-compose.yml` using the same `Dockerfile.bot` image with a different
`command:`.
