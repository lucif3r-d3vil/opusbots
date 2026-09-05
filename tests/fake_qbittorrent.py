"""
A fake qBittorrent Web API v2 server used by the test suite and for local
development of the config panel.

Run it standalone to try the web panel without a real qBittorrent install::

    python -m tests.fake_qbittorrent --port 8080 --version v5.1.0
    # then in the panel: Host 127.0.0.1, Port 8080, admin / adminadmin

It faithfully reproduces the bits that matter:

* ``Ok.`` / ``Fails.`` login bodies and the ``SID`` cookie,
* the IP ban after five failed logins (HTTP 403),
* qBittorrent 5.x (``torrents/stop|start``, Web API 2.11.x) versus 4.x
  (``torrents/pause|resume``),
* "bypass authentication" mode, where no login is needed at all.
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote_plus

BAN_MESSAGE = "Your IP address has been banned after too many failed authentication attempts."

DEFAULTS = {
    "user": "admin",
    "password": "adminadmin",
    "version": "v5.1.0",
    "api_version": "2.11.4",     # 2.11+ behaves like qBittorrent 5.x
    "bypass_auth": False,
    "ban_threshold": 5,
    "banned": False,
    "fail_count": 0,
    "sessions": set(),
    "requests": [],
    "known_categories": {"radarr", "tv-sonarr"},
}

TORRENTS = [
    {
        "hash": "abc123",
        "name": "Ubuntu 24.04 ISO",
        "size": 4 * 1024 ** 3,
        "progress": 0.42,
        "dlspeed": 2 * 1024 ** 2,
        "eta": 120,
        "state": "downloading",
        "category": "radarr",
    }
]


class FakeQBit(BaseHTTPRequestHandler):
    """Minimal qBittorrent Web API v2 stand-in."""

    state = dict(DEFAULTS)

    # -- plumbing ---------------------------------------------------------- #
    def log_message(self, *args):  # keep pytest and the console quiet
        pass

    @classmethod
    def reset(cls, **overrides):
        cls.state = {k: (set(v) if isinstance(v, set) else list(v) if isinstance(v, list) else v)
                     for k, v in DEFAULTS.items()}
        cls.state.update(overrides)

    def _record(self, entry):
        self.state["requests"].append(entry)

    def _authorized(self):
        if self.state["bypass_auth"]:
            return True
        sid = ""
        for part in self.headers.get("Cookie", "").split(";"):
            if part.strip().startswith("SID="):
                sid = part.strip()[4:]
        return sid in self.state["sessions"]

    def _reply(self, code, body, headers=None):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=UTF-8")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length).decode("utf-8", "replace") if length else ""

    # -- routes ------------------------------------------------------------ #
    def do_GET(self):
        path = self.path.split("?")[0]
        self._record("GET " + path)

        if self.state["banned"]:
            return self._reply(403, BAN_MESSAGE)
        if not path.startswith("/api/v2/"):
            # Wrong URL base / wrong port: a real qBittorrent answers 404 here.
            return self._reply(404, "Not Found.")
        if not self._authorized():
            return self._reply(403, "Forbidden.")

        if path == "/api/v2/app/version":
            return self._reply(200, self.state["version"])
        if path == "/api/v2/app/webapiVersion":
            return self._reply(200, self.state["api_version"])
        if path == "/api/v2/torrents/info":
            return self._reply(200, json.dumps(TORRENTS).encode())
        return self._reply(404, "Not Found.")

    def do_POST(self):
        path = self.path.split("?")[0]
        self._record("POST " + path)
        body = self._body()

        if self.state["banned"]:
            return self._reply(403, BAN_MESSAGE)
        if not path.startswith("/api/v2/"):
            return self._reply(404, "Not Found.")

        if path == "/api/v2/auth/login":
            params = dict(pair.split("=", 1) for pair in body.split("&") if "=" in pair)
            user = unquote_plus(params.get("username", ""))
            password = unquote_plus(params.get("password", ""))
            if user == self.state["user"] and password == self.state["password"]:
                sid = "SID-%d" % (len(self.state["sessions"]) + 1)
                self.state["sessions"].add(sid)
                self.state["fail_count"] = 0
                return self._reply(200, "Ok.", {"Set-Cookie": f"SID={sid}; path=/; HttpOnly"})
            self.state["fail_count"] += 1
            if self.state["fail_count"] >= self.state["ban_threshold"]:
                self.state["banned"] = True
                return self._reply(403, BAN_MESSAGE)
            return self._reply(200, "Fails.")

        if path == "/api/v2/auth/logout":
            return self._reply(200, "Ok.")

        if not self._authorized():
            return self._reply(403, "Forbidden.")

        if path == "/api/v2/torrents/add":
            # multipart uploads are not parsed here; the form fields the tests
            # care about (category) arrive urlencoded.
            if "category=does-not-exist" in body:
                return self._reply(200, "Fails.")
            return self._reply(200, "Ok.")

        modern = path in ("/api/v2/torrents/stop", "/api/v2/torrents/start")
        legacy = path in ("/api/v2/torrents/pause", "/api/v2/torrents/resume")
        if modern and self.state["api_version"].startswith("2.11"):
            return self._reply(200, "")
        if legacy and not self.state["api_version"].startswith("2.11"):
            return self._reply(200, "")
        if modern or legacy:
            return self._reply(404, "Not Found.")

        return self._reply(404, "Not Found.")


def start_server(host="127.0.0.1", port=0, **state):
    """Start a fake qBittorrent in a daemon thread. Returns the server object."""
    FakeQBit.reset(**state)
    server = ThreadingHTTPServer((host, port), FakeQBit)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    server.opusbots_thread = thread
    return server


def stop_server(server):
    server.shutdown()
    server.server_close()
    getattr(server, "opusbots_thread", None) and server.opusbots_thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description="Fake qBittorrent Web API for local development")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="adminadmin")
    parser.add_argument("--version", default="v5.1.0")
    parser.add_argument("--api-version", default="2.11.4", help="use 2.9.3 to emulate qBittorrent 4.x")
    parser.add_argument("--bypass-auth", action="store_true")
    args = parser.parse_args()

    server = start_server(
        host=args.host, port=args.port, user=args.user, password=args.password,
        version=args.version, api_version=args.api_version, bypass_auth=args.bypass_auth,
    )
    print(f"Fake qBittorrent {args.version} (Web API {args.api_version}) on "
          f"http://{args.host}:{server.server_address[1]}  --  {args.user}/{args.password}")
    try:
        server.opusbots_thread.join()
    except KeyboardInterrupt:
        stop_server(server)


if __name__ == "__main__":
    main()
