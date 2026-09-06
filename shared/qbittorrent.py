"""
qBittorrent Web API v2 client for OpusBots.

Why this module exists
----------------------
qBittorrent is driven through its Web API (``/api/v2/...``) with a session
cookie (``SID``) handed out by ``auth/login``.  Three things routinely break
that flow on a homelab, and all three used to surface as the same useless
"qBittorrent authentication failed. Check username and password." message:

1. **Address format.**  People type the address exactly like they type it in
   Radarr/Sonarr -- ``192.168.1.50:30024``, host and port, no scheme.
   ``requests`` refuses a scheme-less URL, so nothing was ever sent.
2. **Login storms -> IP ban.**  qBittorrent bans an IP for an hour after five
   failed logins.  The bot used to log in again for *every single API call*
   (each ``/status`` refresh, each dashboard button), which burns that budget
   instantly.  Once banned, every later attempt -- even with the correct
   password -- answers HTTP 403 "Your IP address has been banned after too many
   failed authentication attempts", which was reported as a bad password.
3. **Version drift.**  qBittorrent 5.x renamed ``torrents/pause|resume`` to
   ``torrents/stop|start`` (and the ``pausedDL``/``pausedUP`` states to
   ``stoppedDL``/``stoppedUP``), so pause/resume silently 404'd on v5.

This client normalizes the address, logs in **once** per credential set and
caches the authenticated session, backs off after a rejected login so it can
never extend a ban, classifies every failure into something a human can act on,
and speaks both the 4.x and 5.x API dialects.
"""

import hashlib
import re
import threading
import time
from collections import OrderedDict

import requests

API_PREFIX = "/api/v2/"
DEFAULT_TIMEOUT = 10
USER_AGENT = "OpusBots/1.0 (+https://github.com/lucif3r-d3vil/opusbots)"

# How long we refuse to retry a login that qBittorrent rejected.  This is what
# stops a wrong password from turning into a one hour IP ban.
LOGIN_COOLDOWN = 120
BAN_COOLDOWN = 900

MAX_CACHED_CLIENTS = 8

BAN_HINT = (
    "qBittorrent bans an IP for ~1 hour after 5 failed logins. Wait for the ban to expire, "
    "clear it in qBittorrent > Tools > Options > Web User Interface > Security (Ban duration), "
    "or restart the qBittorrent container. Then test once more -- OpusBots deliberately does "
    "not retry on its own, because every attempt restarts the ban timer."
)

# host[:port] -- also matches bracketed IPv6 literals such as [::1]:8080
_HOST_PORT_RE = re.compile(r"^(?P<host>\[[^\]]+\]|[^:]+)(?::(?P<port>\d+))?$")
_VERSION_RE = re.compile(r"^v?\d+\.\d+")

# Torrent states, qBittorrent 4.x and 5.x spellings side by side.
DOWNLOADING_STATES = {
    "downloading", "forcedDL", "metaDL", "forcedMetaDL", "stalledDL",
    "queuedDL", "allocating", "checkingDL", "moving",
}
SEEDING_STATES = {"uploading", "forcedUP", "stalledUP", "queuedUP", "checkingUP"}
STOPPED_STATES = {"pausedDL", "pausedUP", "stoppedDL", "stoppedUP"}


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class QBitError(Exception):
    """Base class for every qBittorrent failure.

    ``message`` is the short one-liner, ``hint`` an optional second line that
    tells the user what to actually do about it.
    """

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self):
        return self.message

    @property
    def full(self):
        return f"{self.message}\n{self.hint}" if self.hint else self.message


class QBitNotConfiguredError(QBitError):
    """No usable host/port in config.json yet."""


class QBitConnectionError(QBitError):
    """The address could not be reached (DNS, refused, timeout, TLS)."""


class QBitAuthError(QBitError):
    """qBittorrent rejected the credentials."""


class QBitBannedError(QBitAuthError):
    """qBittorrent temporarily banned our IP after too many failed logins."""


class QBitForbiddenError(QBitError):
    """HTTP 403 that is *not* a credential problem (host header validation)."""


class QBitNotFoundError(QBitError):
    """HTTP 404 -- the URL does not point at a qBittorrent Web API."""


def error_text(exc):
    """Human readable, hint included, for logs / Telegram / the web panel."""
    if isinstance(exc, QBitError):
        return exc.full
    return str(exc)


# --------------------------------------------------------------------------- #
# Address handling
# --------------------------------------------------------------------------- #
def split_host_port(value):
    """Split a qBittorrent address into (host, port) the way Radarr shows them.

    ``"http://192.168.1.50:30024"``  -> ``("http://192.168.1.50", "30024")``
    ``"192.168.1.50:30024"``          -> ``("192.168.1.50", "30024")``
    ``"qbit.local"``                  -> ``("qbit.local", "")``

    The scheme (if the user typed one) stays on the host so HTTPS setups keep
    working.  Returns ``("", "")`` for empty input and never raises.
    """
    raw = (value or "").strip()
    if not raw:
        return "", ""

    scheme = ""
    match = re.match(r"^(https?://)", raw, re.IGNORECASE)
    if match:
        scheme = match.group(1).lower()
        raw = raw[match.end():]

    hostport, sep, path = raw.partition("/")
    match = _HOST_PORT_RE.match(hostport.strip())
    if not match:
        return raw.strip(), ""

    host = match.group("host")
    port = match.group("port") or ""
    host_value = f"{scheme}{host}"
    if sep and path.strip("/"):
        host_value += "/" + path.strip("/")
    return host_value, port


def build_base_url(host, port=None, url_base=""):
    """Build the canonical qBittorrent base URL from loose user input.

    Accepts everything a human might paste into the web panel:
    ``192.168.1.50:30024``, ``http://192.168.1.50:30024``, ``qbit:8080``,
    ``https://qbit.example.com/qbittorrent/``, ``[::1]:8080``, and a separate
    ``port`` / ``url_base`` (Radarr's "URL Base") when given.

    A port written inside the host wins over the separate ``port`` argument.
    """
    raw = (host or "").strip()
    if not raw:
        raise QBitNotConfiguredError(
            "qBittorrent host is not configured.",
            "Open the OpusBots web panel (port 8090) and enter the same Host and "
            "Port you use for qBittorrent in Radarr/Sonarr.",
        )

    # Collapse every kind of whitespace: copy/paste from a notes app or the
    # qBittorrent options dialog often drags newlines and spaces along.
    raw = "".join(raw.split())

    scheme = "http"
    match = re.match(r"^(https?)://", raw, re.IGNORECASE)
    if match:
        scheme = match.group(1).lower()
        raw = raw[match.end():]
    elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", raw):
        raise QBitError(
            f"Unsupported scheme in qBittorrent host '{host}'.",
            "Use http:// or https:// -- or leave the scheme out entirely.",
        )

    if "@" in raw:
        raise QBitError(
            f"Do not put credentials in the qBittorrent host ('{host}').",
            "Enter only host[:port] and use the separate Username / Password fields.",
        )

    path = ""
    hostport, sep, rest = raw.partition("/")
    if sep and rest.strip("/"):
        path = "/" + rest.strip("/")

    match = _HOST_PORT_RE.match(hostport)
    if not match or not match.group("host"):
        raise QBitError(
            f"Could not understand the qBittorrent host '{host}'.",
            "Expected something like 192.168.1.50, qbit:8080 or https://qbit.example.com",
        )

    hostname = match.group("host")
    port_value = match.group("port") or ""
    if not port_value and port not in (None, ""):
        port_value = str(port).strip()

    if port_value:
        try:
            port_number = int(port_value)
        except ValueError:
            raise QBitError(
                f"qBittorrent port '{port_value}' is not a number.",
                "Use the port from qBittorrent > Tools > Options > Web User Interface.",
            ) from None
        if not 1 <= port_number <= 65535:
            raise QBitError(f"qBittorrent port '{port_number}' is out of range (1-65535).")
        port_value = str(port_number)

    base_path = (url_base or "").strip()
    if base_path:
        base_path = "/" + base_path.strip().strip("/")
        if path and path != base_path:
            path = path.rstrip("/") + base_path
        else:
            path = base_path

    # People paste the whole API URL sometimes; drop the trailing API bits.
    path = re.sub(r"/(?:api(?:/v2)?|gui|webui)/?$", "", path, flags=re.IGNORECASE)

    url = f"{scheme}://{hostname}"
    if port_value:
        url += f":{port_value}"
    return url + path


# --------------------------------------------------------------------------- #
# Session cache + login back-off
# --------------------------------------------------------------------------- #
_clients = OrderedDict()
_login_failures = {}
_cache_lock = threading.RLock()


def _make_error(cls, message, hint=""):
    err = cls(message)
    err.hint = hint
    return err


def _note_failure(key, error, cooldown):
    """Remember a rejected login so we stop hammering qBittorrent."""
    with _cache_lock:
        entry = _login_failures.get(key)
        attempts = (entry or {}).get("attempts", 0) + 1
        _login_failures[key] = {
            "until": time.time() + cooldown,
            "message": error.message,
            "hint": error.hint,
            "type": type(error),
            "attempts": attempts,
        }


def _clear_failure(key):
    with _cache_lock:
        _login_failures.pop(key, None)


def _raise_cached_failure(failure):
    wait = int(max(0, failure["until"] - time.time()))
    message = failure["message"]
    if wait:
        message += (
            f" OpusBots will not retry for another {wait}s so the failure counter "
            "in qBittorrent can reset."
        )
    raise _make_error(failure["type"], message, failure.get("hint", ""))


def clear_client_cache(clear_backoff=True):
    """Drop every cached session (and optionally the login back-off timers)."""
    with _cache_lock:
        _clients.clear()
        if clear_backoff:
            _login_failures.clear()


def active_ban(cfg):
    """Seconds left on a recorded qBittorrent IP ban for these credentials, else 0.

    Lets the web panel keep reporting a ban (with its countdown) without sending
    another request that would only restart qBittorrent's ban timer.
    """
    try:
        key = QBittorrentClient(cfg).key
    except QBitError:
        return 0
    with _cache_lock:
        failure = _login_failures.get(key)
        if not failure or failure["until"] <= time.time():
            return 0
        if issubclass(failure["type"], QBitBannedError):
            return int(failure["until"] - time.time())
    return 0


def get_configured_url(cfg):
    """The base URL this config would talk to, or "" when not configured."""
    q = (cfg or {}).get("qbittorrent") or {}
    try:
        return build_base_url(q.get("host"), q.get("port"), q.get("url_base"))
    except QBitError:
        return ""


def cached_client_count():
    with _cache_lock:
        return len(_clients)


def login_backoff_remaining(key):
    """Seconds left on a login back-off, 0 when there is none."""
    with _cache_lock:
        failure = _login_failures.get(key)
        if not failure:
            return 0
        return int(max(0, failure["until"] - time.time()))


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class QBittorrentClient:
    """Small, defensive client for the qBittorrent Web API v2."""

    def __init__(self, cfg=None, base_url=None, username=None, password=None,
                 verify_tls=None, timeout=DEFAULT_TIMEOUT, session=None):
        q = {}
        if cfg:
            q = cfg.get("qbittorrent") or {}

        self.base_url = (base_url or build_base_url(
            q.get("host"), q.get("port"), q.get("url_base"),
        )).rstrip("/")
        self.username = (q.get("user", "") if username is None else username).strip()
        self.password = q.get("pass", "") if password is None else password
        self.password = "" if self.password is None else str(self.password)

        if verify_tls is None:
            verify_tls = q.get("verify_tls", True)
        if isinstance(verify_tls, str):
            verify_tls = verify_tls.strip().lower() not in ("0", "false", "no", "off", "")
        self.verify_tls = bool(verify_tls)

        try:
            self.timeout = float(timeout or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT

        # Created on first use: building a client is cheap enough to do on every
        # call just to look its cache key up.
        self._session = session

        self._logged_in = False
        self.auth_bypassed = False
        self.app_version = None
        self.api_version = None
        # None = unknown, True = 5.x (start/stop), False = 4.x (resume/pause)
        self._uses_start_stop = None
        self._lock = threading.RLock()

    # -- identity ---------------------------------------------------------- #
    @property
    def session(self):
        """The requests.Session, created on first use."""
        if self._session is None:
            self._session = requests.Session()
        return self._session

    @property
    def key(self):
        digest = hashlib.sha256(self.password.encode("utf-8")).hexdigest()[:16]
        return (self.base_url, self.username, digest, self.verify_tls)

    def __repr__(self):
        return f"<QBittorrentClient {self.base_url} user={self.username or '-'}>"

    # -- low level transport ----------------------------------------------- #
    def url(self, endpoint):
        return self.base_url + API_PREFIX + endpoint.lstrip("/")

    def _send(self, method, endpoint, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        kwargs["verify"] = self.verify_tls
        # Sent per request (not on the session) so they also apply to sessions
        # that are handed in from the outside.  Some reverse proxies and
        # qBittorrent's own host/CSRF checks expect a same-origin Referer.
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("User-Agent", USER_AGENT)
        headers.setdefault("Referer", self.base_url + "/")
        kwargs["headers"] = headers
        if not self.verify_tls:
            # The user explicitly opted out of verification; keep the logs clean.
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:  # pragma: no cover - urllib3 always ships with requests
                pass
        return self.session.request(method, self.url(endpoint), **kwargs)

    def _connection_error(self, exc):
        text = str(exc).lower()
        host = self.base_url.split("//", 1)[-1].split("/", 1)[0]

        if isinstance(exc, requests.exceptions.SSLError) or "ssl" in text or "certificate" in text:
            return _make_error(
                QBitConnectionError,
                f"TLS error while contacting qBittorrent at {self.base_url}.",
                "If qBittorrent uses a self-signed certificate, either switch the host "
                "to http:// or tick 'Skip TLS certificate verification' in the web panel.",
            )
        if isinstance(exc, requests.exceptions.Timeout) or "timed out" in text:
            reason = "the connection timed out"
        elif "name or service not known" in text or "nodename nor servname" in text \
                or "getaddrinfo" in text or "name resolution" in text or "failed to resolve" in text:
            reason = f"the hostname '{host.split(':')[0]}' could not be resolved"
        elif "refused" in text or "no route to host" in text or "unreachable" in text:
            reason = "the connection was refused (nothing is listening on that host:port)"
        else:
            reason = str(exc)[:160]

        hint = (
            "Use the exact Host and Port from qBittorrent > Tools > Options > Web User "
            "Interface -- the same values Radarr/Sonarr use."
        )
        hostname = host.split(":", 1)[0].strip("[]")
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            hint = (
                "Inside Docker 'localhost' is the bot container itself, not your server. "
                "Use the LAN IP (e.g. 192.168.1.50), the container/service name "
                "(e.g. qbittorrent:8080) or host.docker.internal instead. " + hint
            )
        return _make_error(
            QBitConnectionError,
            f"Could not reach qBittorrent at {self.base_url}: {reason}.",
            hint,
        )

    # -- authentication ---------------------------------------------------- #
    def login(self, force=False):
        """Make sure we hold a valid SID. Returns True once authorized.

        Raises a :class:`QBitError` subclass that explains *which* knob to turn
        when it does not work.
        """
        with self._lock:
            if self._logged_in and not force:
                return True
            if self._probe_auth_bypass():
                return True
            self._perform_login()
            return True

    def _probe_auth_bypass(self):
        """GET app/version: 200 means qBittorrent already accepts this client.

        qBittorrent answers 403 when a SID is required and 200 when the request
        comes from localhost or a whitelisted subnet ("bypass authentication").
        The version comes for free, which is why we probe instead of guessing.
        """
        try:
            probe = self._send("GET", "app/version")
        except requests.RequestException as exc:
            raise self._connection_error(exc) from None

        body = (probe.text or "").strip()
        if probe.status_code == 200 and _VERSION_RE.match(body):
            self._logged_in = True
            self.auth_bypassed = True
            self.app_version = body
            _clear_failure(self.key)
            return True

        error = self._classify_probe(probe, body)
        if error is not None:
            self._fail(error)
        return False

    def _classify_probe(self, probe, body):
        """Turn a non-200 version probe into a precise error (or None to log in)."""
        lowered = body.lower()

        if "banned" in lowered:
            # Already banned: do not even attempt a login, that only restarts
            # qBittorrent's ban timer.
            return _make_error(
                QBitBannedError,
                body[:200] or f"qBittorrent at {self.base_url} has banned this IP address.",
                BAN_HINT,
            )
        if probe.status_code == 200 and body and "<html" in lowered:
            return _make_error(
                QBitNotFoundError,
                f"{self.base_url} answered with a web page instead of the qBittorrent API.",
                "That port is probably not the qBittorrent Web UI, or a reverse proxy is in "
                "front of it. Check the port, and set 'URL Base' if qBittorrent lives behind "
                "a sub-path such as /qbittorrent.",
            )
        if probe.status_code == 404:
            return _make_error(
                QBitNotFoundError,
                f"{self.base_url}/api/v2/app/version does not exist (HTTP 404).",
                "The host/port is reachable but it is not a qBittorrent Web API. Verify the "
                "port from qBittorrent > Options > Web User Interface, and set 'URL Base' if "
                "it sits behind a sub-path.",
            )
        # 403/401 and anything else: a login is expected, carry on.
        return None

    def _perform_login(self):
        """POST auth/login and classify every possible answer."""
        if not self.username and not self.password:
            self._fail(_make_error(
                QBitAuthError,
                "qBittorrent asked for a login but no username/password is configured.",
                "Enter the qBittorrent Web UI username and password in the OpusBots web panel "
                "(default user is 'admin'). qBittorrent 5.x generates a random password on "
                "first start and prints it to its log.",
            ))

        try:
            response = self._send("POST", "auth/login", data={
                "username": self.username,
                "password": self.password,
            })
        except requests.RequestException as exc:
            raise self._connection_error(exc) from None

        text = (response.text or "").strip()
        lowered = text.lower()

        if response.status_code == 200 and lowered.startswith("ok"):
            self._logged_in = True
            self.auth_bypassed = False
            _clear_failure(self.key)
            return

        if "banned" in lowered:
            self._fail(_make_error(
                QBitBannedError, text[:200] or "qBittorrent has banned this IP address.", BAN_HINT,
            ))
        if response.status_code == 403:
            # A 403 that is not about credentials: qBittorrent rejected the
            # request itself (host header validation, domain list, ...).
            self._fail(_make_error(
                QBitForbiddenError,
                f"qBittorrent refused the request with HTTP 403 ({text[:80] or 'no body'}).",
                "If the Web UI opens fine in your browser, qBittorrent is rejecting this "
                "client's Host header or IP. Whitelist the bot's subnet under Options > Web "
                "User Interface > Security, or extend/disable host header validation "
                "(WebUI\\HostHeaderValidation, WebUI\\ServerDomains in qBittorrent.conf).",
            ))
        if lowered.startswith("fails") or response.status_code == 401:
            self._fail(_make_error(
                QBitAuthError,
                "qBittorrent rejected the username or password.",
                "Re-check them in qBittorrent > Tools > Options > Web User Interface. Note: 5 "
                "failed logins get this IP banned for ~1 hour, so OpusBots waits instead of "
                "retrying in a loop.",
            ))
        if response.status_code == 404:
            self._fail(_make_error(
                QBitNotFoundError,
                f"{self.base_url}/api/v2/auth/login does not exist (HTTP 404).",
                "Wrong port, or a missing URL Base for a reverse-proxied qBittorrent.",
            ))
        if "<html" in lowered:
            self._fail(_make_error(
                QBitNotFoundError,
                f"qBittorrent login at {self.base_url} returned a web page, not 'Ok.'",
                "A reverse proxy is answering instead of qBittorrent. Set 'URL Base' to the "
                "sub-path qBittorrent is served from.",
            ))
        self._fail(_make_error(
            QBitAuthError,
            f"Unexpected qBittorrent login response (HTTP {response.status_code}): {text[:120]}",
        ))

    def _fail(self, error, cooldown=LOGIN_COOLDOWN):
        """Record the back-off for this credential set and raise."""
        if isinstance(error, QBitBannedError):
            cooldown = BAN_COOLDOWN
        _note_failure(self.key, error, cooldown)
        raise error

    def logout(self):
        """Best effort logout; never raises."""
        try:
            if self._logged_in and not self.auth_bypassed:
                self._send("POST", "auth/logout")
        except Exception:
            pass
        finally:
            self._logged_in = False

    # -- requests ---------------------------------------------------------- #
    def request(self, method, endpoint, _retried=False, **kwargs):
        """Authenticated request; re-logs in once if the SID went stale."""
        self.login()
        try:
            response = self._send(method, endpoint, **kwargs)
        except requests.RequestException as exc:
            self._logged_in = False
            raise self._connection_error(exc) from None

        if response.status_code == 403 and not _retried and not self.auth_bypassed:
            # Session expired (qBittorrent's default timeout is 1 hour) or the
            # SID cookie was dropped: log in again exactly once.
            self._logged_in = False
            with _cache_lock:
                _login_failures.pop(self.key, None)
            self.login(force=True)
            return self.request(method, endpoint, _retried=True, **kwargs)

        if response.status_code == 403:
            text = (response.text or "").strip().lower()
            if "banned" in text:
                raise _make_error(QBitBannedError, response.text.strip()[:200],
                                  "Clear the ban in qBittorrent > Options > Web UI > Security.")
            raise _make_error(
                QBitForbiddenError,
                f"qBittorrent returned HTTP 403 for {endpoint}.",
                "If the Web UI works in your browser, qBittorrent is probably rejecting the "
                "Host header. Add this address to qBittorrent > Options > Web User Interface "
                "> 'Bypass authentication for clients in whitelisted IP subnets' or disable "
                "Host header validation (WebUI\\HostHeaderValidation) / extend its domain list.",
            )
        return response

    def get_text(self, endpoint, params=None):
        return (self.request("GET", endpoint, params=params).text or "").strip()

    def get_json(self, endpoint, params=None, default=None):
        response = self.request("GET", endpoint, params=params)
        try:
            return response.json()
        except ValueError:
            if default is not None:
                return default
            raise _make_error(
                QBitError,
                f"qBittorrent returned invalid JSON from {endpoint} (HTTP {response.status_code}).",
                (response.text or "")[:160],
            ) from None

    def post(self, endpoint, data=None, files=None):
        return self.request("POST", endpoint, data=data, files=files)

    # -- application ------------------------------------------------------- #
    def fetch_versions(self):
        """Return (app_version, web_api_version), best effort."""
        if not self.app_version:
            try:
                self.app_version = self.get_text("app/version") or "Unknown"
            except QBitError:
                self.app_version = "Unknown"
        if not self.api_version:
            try:
                self.api_version = self.get_text("app/webapiVersion") or "v2"
            except QBitError:
                self.api_version = "v2"
        return self.app_version, self.api_version

    # -- torrents ---------------------------------------------------------- #
    def torrents_info(self, status_filter=None, limit=None, sort=None):
        params = {}
        if status_filter:
            params["filter"] = status_filter
        if limit:
            params["limit"] = limit
        if sort:
            params["sort"] = sort
        data = self.get_json("torrents/info", params=params or None)
        return data if isinstance(data, list) else []

    def add_urls(self, urls, savepath=None, category=None, tags=None, **extra):
        data = {"urls": urls}
        if savepath:
            data["savepath"] = savepath
        if category:
            data["category"] = category
        if tags:
            data["tags"] = tags
        data.update(extra)
        response = self.post("torrents/add", data=data)
        return (response.text or "").strip().lower().startswith("ok")

    def add_torrent_files(self, file_bytes, filename, savepath=None, category=None, tags=None):
        data = {}
        if savepath:
            data["savepath"] = savepath
        if category:
            data["category"] = category
        if tags:
            data["tags"] = tags
        files = {"torrents": (filename, file_bytes, "application/x-bittorrent")}
        response = self.post("torrents/add", data=data, files=files)
        return (response.text or "").strip().lower().startswith("ok")

    def set_torrent_state(self, start, hashes="all"):
        """Start/stop torrents on qBittorrent 5.x, resume/pause on 4.x.

        Returns True when qBittorrent accepted the request.
        """
        modern = ("torrents/start", "torrents/stop")
        legacy = ("torrents/resume", "torrents/pause")
        order = [modern[0 if start else 1], legacy[0 if start else 1]]
        if self._uses_start_stop is False:
            order.reverse()

        last_status = None
        for endpoint in order:
            response = self.post(endpoint, data={"hashes": hashes})
            last_status = response.status_code
            if response.status_code == 404:
                # Endpoint renamed/removed in this qBittorrent version: remember
                # which dialect works so the next call goes straight there.
                self._uses_start_stop = endpoint not in modern
                continue
            self._uses_start_stop = endpoint in modern
            return response.status_code == 200

        raise _make_error(
            QBitNotFoundError,
            f"qBittorrent at {self.base_url} supports neither torrents/start|stop nor "
            f"torrents/resume|pause (HTTP {last_status}).",
            "That does not look like a qBittorrent Web API endpoint.",
        )


# --------------------------------------------------------------------------- #
# Cached access
# --------------------------------------------------------------------------- #
def client_for(cfg, force_fresh=False):
    """Return a (cached, already authenticated on demand) client for ``cfg``.

    ``force_fresh`` is meant for the "Test Connection" button in the web panel:
    it ignores the back-off timer so a human can retry immediately.
    """
    client = QBittorrentClient(cfg)
    key = client.key

    with _cache_lock:
        if force_fresh:
            _login_failures.pop(key, None)
            _clients.pop(key, None)

        failure = _login_failures.get(key)
        if failure:
            if failure["until"] > time.time():
                _raise_cached_failure(failure)
            _login_failures.pop(key, None)

        cached = _clients.get(key)
        if cached is not None:
            _clients.move_to_end(key)
            return cached

        _clients[key] = client
        while len(_clients) > MAX_CACHED_CLIENTS:
            _clients.popitem(last=False)
        return client


def test_connection(cfg, force_fresh=True):
    """Connect, log in and read the version. Returns ``(ok, message)``."""
    details = diagnose(cfg, force_fresh=force_fresh)
    message = details["message"]
    if details.get("hint"):
        message = f"{message}\n{details['hint']}"
    return details["ok"], message


def diagnose(cfg, force_fresh=True):
    """Like :func:`test_connection` but returns a structured report.

    Used by the web panel so it can show the exact URL that was tried plus an
    actionable hint instead of a bare "authentication failed".
    """
    report = {
        "ok": False,
        "message": "",
        "hint": "",
        "base_url": "",
        "version": "",
        "api_version": "",
        "auth_bypassed": False,
    }
    try:
        client = client_for(cfg, force_fresh=force_fresh)
    except QBitError as exc:
        report.update(message=exc.message, hint=exc.hint)
        return report

    report["base_url"] = client.base_url
    try:
        client.login(force=force_fresh)
        version, api_version = client.fetch_versions()
    except QBitError as exc:
        report.update(message=exc.message, hint=exc.hint)
        return report
    except Exception as exc:  # pragma: no cover - defensive
        report.update(message=str(exc))
        return report

    report.update({
        "ok": True,
        "version": version,
        "api_version": api_version,
        "auth_bypassed": client.auth_bypassed,
        "message": f"Connected to qBittorrent {version} (Web API {api_version}) at {client.base_url}",
    })
    if client.auth_bypassed:
        report["hint"] = (
            "Authentication is bypassed for this client (qBittorrent Web UI > Security > "
            "'Bypass authentication for clients on localhost / whitelisted IP subnets')."
        )
    return report
