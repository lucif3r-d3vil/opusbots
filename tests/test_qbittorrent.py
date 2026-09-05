"""
Unit tests for the qBittorrent client: address normalisation, login error
classification, session caching/back-off and the 4.x vs 5.x endpoint dialects.

No sockets are involved -- a scripted fake ``requests.Session`` stands in for
qBittorrent.  See tests/test_qbittorrent_server.py for the real HTTP version.
"""

import pytest
import requests
from unittest.mock import patch

from shared import qbittorrent
from shared.qbittorrent import (
    QBittorrentClient,
    QBitAuthError,
    QBitBannedError,
    QBitConnectionError,
    QBitError,
    QBitForbiddenError,
    QBitNotFoundError,
    QBitNotConfiguredError,
    build_base_url,
    client_for,
    clear_client_cache,
    error_text,
    split_host_port,
)


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.cookies = {}

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


class FakeSession:
    """Scripted stand-in for requests.Session."""

    def __init__(self, script=()):
        self.headers = {}
        self.calls = []
        self.script = list(script)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.script:
            return FakeResponse(404, "Not Found.")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def paths(self):
        return [url.split("/api/v2/")[-1] for _, url, _ in self.calls]


@pytest.fixture(autouse=True)
def clean_cache():
    clear_client_cache()
    yield
    clear_client_cache()


def make_client(script=(), **kwargs):
    session = FakeSession(script)
    kwargs.setdefault("base_url", "http://qbit.local:8080")
    kwargs.setdefault("username", "admin")
    kwargs.setdefault("password", "adminadmin")
    client = QBittorrentClient(session=session, **kwargs)
    return client, session


# --------------------------------------------------------------------------- #
# Address normalisation -- the "same host and port as Radarr" bug
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("host,port,url_base,expected", [
    ("192.168.1.50:30024", None, "", "http://192.168.1.50:30024"),
    ("192.168.1.50", "30024", "", "http://192.168.1.50:30024"),
    ("http://192.168.1.50:30024", None, "", "http://192.168.1.50:30024"),
    ("http://192.168.1.50:30024/", None, "", "http://192.168.1.50:30024"),
    ("HTTP://Qbit.Local:8080", None, "", "http://Qbit.Local:8080"),
    ("https://qbit.example.com", None, "", "https://qbit.example.com"),
    ("https://qbit.example.com", "443", "/qbittorrent", "https://qbit.example.com:443/qbittorrent"),
    ("  10.0.0.7:8080  ", None, "", "http://10.0.0.7:8080"),
    ("10.0.0.7\n:8080", None, "", "http://10.0.0.7:8080"),
    ("http://10.0.0.7:8080/api/v2", None, "", "http://10.0.0.7:8080"),
    ("http://10.0.0.7:8080/gui/", None, "", "http://10.0.0.7:8080"),
    ("qbittorrent", "8080", "", "http://qbittorrent:8080"),
    ("[::1]:8080", None, "", "http://[::1]:8080"),
    ("192.168.1.50:30024", "8080", "", "http://192.168.1.50:30024"),  # inline port wins
    ("localhost", None, "", "http://localhost"),
])
def test_build_base_url(host, port, url_base, expected):
    assert build_base_url(host, port, url_base) == expected


@pytest.mark.parametrize("host,port", [
    ("", None),
    ("   ", None),
    (None, None),
])
def test_build_base_url_requires_a_host(host, port):
    with pytest.raises(QBitNotConfiguredError):
        build_base_url(host, port)


@pytest.mark.parametrize("host,port,message", [
    ("ftp://10.0.0.5", None, "Unsupported scheme"),
    ("http://admin:pw@10.0.0.5:8080", None, "credentials"),
    ("10.0.0.5", "abc", "not a number"),
    ("10.0.0.5", "70000", "out of range"),
    ("10.0.0.5:70000", None, "out of range"),
])
def test_build_base_url_rejects_nonsense(host, port, message):
    with pytest.raises(QBitError) as excinfo:
        build_base_url(host, port)
    assert message in str(excinfo.value)


@pytest.mark.parametrize("value,expected", [
    ("http://192.168.1.50:30024", ("http://192.168.1.50", "30024")),
    ("https://192.168.1.50:30024", ("https://192.168.1.50", "30024")),
    ("192.168.1.50:30024", ("192.168.1.50", "30024")),
    ("192.168.1.50", ("192.168.1.50", "")),
    ("", ("", "")),
    (None, ("", "")),
    ("http://[::1]:8080", ("http://[::1]", "8080")),
])
def test_split_host_port(value, expected):
    assert split_host_port(value) == expected


def test_client_builds_url_from_cfg():
    client = QBittorrentClient({"qbittorrent": {"host": "192.168.1.50", "port": "30024",
                                                "user": "admin", "pass": "pw"}})
    assert client.base_url == "http://192.168.1.50:30024"
    assert client.url("auth/login") == "http://192.168.1.50:30024/api/v2/auth/login"


def test_verify_tls_defaults_to_true_and_can_be_disabled():
    client, session = make_client([FakeResponse(200, "v5.1.0")], verify_tls=False)
    client.login()
    assert session.calls[0][2]["verify"] is False

    client, session = make_client([FakeResponse(200, "v5.1.0")])
    client.login()
    assert session.calls[0][2]["verify"] is True


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def test_login_success_sets_a_referer_and_user_agent():
    client, session = make_client([
        FakeResponse(403, "Forbidden."),          # probe: a SID is required
        FakeResponse(200, "Ok."),                 # auth/login
    ])
    assert client.login() is True
    assert client.auth_bypassed is False
    # Every request carries a same-origin Referer and an honest User-Agent.
    for _, _, kwargs in session.calls:
        assert kwargs["headers"]["Referer"] == "http://qbit.local:8080/"
        assert "OpusBots" in kwargs["headers"]["User-Agent"]
    assert session.paths == ["app/version", "auth/login"]
    assert session.calls[1][2]["data"] == {"username": "admin", "password": "adminadmin"}


def test_login_is_idempotent():
    client, session = make_client([FakeResponse(403, "Forbidden."), FakeResponse(200, "Ok.")])
    client.login()
    client.login()
    assert len(session.calls) == 2


def test_login_accepts_lowercase_ok():
    client, _ = make_client([FakeResponse(403, "Forbidden."), FakeResponse(200, "ok.")])
    assert client.login() is True


def test_auth_bypass_skips_login_entirely():
    client, session = make_client([FakeResponse(200, "v5.1.0")])
    assert client.login() is True
    assert client.auth_bypassed is True
    assert client.app_version == "v5.1.0"
    assert session.paths == ["app/version"]


def test_wrong_password_raises_auth_error():
    client, _ = make_client([FakeResponse(403, "Forbidden."), FakeResponse(200, "Fails.")])
    with pytest.raises(QBitAuthError) as excinfo:
        client.login()
    assert "username or password" in str(excinfo.value)
    assert "banned" in excinfo.value.hint.lower()


def test_banned_ip_is_reported_as_a_ban():
    ban_text = "Your IP address has been banned after too many failed authentication attempts."
    client, _ = make_client([FakeResponse(403, ban_text)])
    with pytest.raises(QBitBannedError) as excinfo:
        client.login()
    assert "banned" in str(excinfo.value).lower()
    assert "Ban duration" in excinfo.value.hint


def test_ban_detected_on_the_login_post_too():
    client, _ = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(403, "Your IP address has been banned after too many failed attempts."),
    ])
    with pytest.raises(QBitBannedError):
        client.login()


def test_403_on_login_is_host_header_validation_not_a_ban():
    """A 403 without 'banned' means qBittorrent rejected the request itself."""
    client, _ = make_client([FakeResponse(403, "Forbidden."), FakeResponse(403, "Forbidden.")])
    with pytest.raises(QBitForbiddenError) as excinfo:
        client.login()
    assert "403" in str(excinfo.value)
    assert "HostHeaderValidation" in excinfo.value.hint


def test_missing_credentials_are_not_sent_as_a_failed_login():
    client, session = make_client([FakeResponse(403, "Forbidden.")], username="", password="")
    with pytest.raises(QBitAuthError) as excinfo:
        client.login()
    assert "no username/password" in str(excinfo.value)
    assert session.paths == ["app/version"], "must not burn a login attempt"


def test_404_explains_the_url_base():
    client, _ = make_client([FakeResponse(404, "Not Found.")])
    with pytest.raises(QBitNotFoundError) as excinfo:
        client.login()
    assert "404" in str(excinfo.value)
    assert "URL Base" in excinfo.value.hint


def test_html_response_blames_the_reverse_proxy():
    client, _ = make_client([FakeResponse(200, "<html><head>Login</head></html>")])
    with pytest.raises(QBitNotFoundError) as excinfo:
        client.login()
    assert "web page" in str(excinfo.value)
    assert "reverse proxy" in excinfo.value.hint.lower()


def test_unexpected_login_body_is_surfaced():
    client, _ = make_client([FakeResponse(403, "Forbidden."), FakeResponse(500, "boom")])
    with pytest.raises(QBitAuthError) as excinfo:
        client.login()
    assert "HTTP 500" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Connection level errors
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("exc,expected,hint", [
    (requests.exceptions.SSLError("certificate verify failed"), "TLS error", "self-signed"),
    (requests.exceptions.ConnectTimeout("timed out"), "timed out", "Radarr"),
    (requests.exceptions.ConnectionError("HTTPConnectionPool: Max retries exceeded "
                                         "(Caused by NameResolutionError('Failed to resolve'))"),
     "could not be resolved", "Radarr"),
    (requests.exceptions.ConnectionError("Connection refused"), "refused", "Radarr"),
])
def test_connection_errors_are_classified(exc, expected, hint):
    client, _ = make_client([exc])
    with pytest.raises(QBitConnectionError) as excinfo:
        client.login()
    assert expected in str(excinfo.value)
    assert hint in excinfo.value.hint


def test_localhost_gets_the_docker_hint():
    client, _ = make_client(
        [requests.exceptions.ConnectionError("Connection refused")],
        base_url="http://localhost:8080",
    )
    with pytest.raises(QBitConnectionError) as excinfo:
        client.login()
    assert "bot container itself" in excinfo.value.hint
    assert "host.docker.internal" in excinfo.value.hint


def test_error_text_includes_the_hint():
    err = QBitAuthError("nope", hint="do this")
    assert error_text(err) == "nope\ndo this"
    assert error_text(RuntimeError("plain")) == "plain"


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
def test_stale_session_relogs_in_once():
    client, session = make_client([
        FakeResponse(403, "Forbidden."),   # probe
        FakeResponse(200, "Ok."),          # login
        FakeResponse(403, "Forbidden."),   # the real call: SID expired
        FakeResponse(403, "Forbidden."),   # probe again
        FakeResponse(200, "Ok."),          # login again
        FakeResponse(200, "[]", json_data=[]),
    ])
    assert client.torrents_info() == []
    assert session.paths.count("auth/login") == 2


def test_forbidden_after_relogin_mentions_host_header_validation():
    client, _ = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(403, "Forbidden."),
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(403, "Forbidden."),
    ])
    with pytest.raises(QBitForbiddenError) as excinfo:
        client.torrents_info()
    assert "Host header" in excinfo.value.hint


def test_invalid_json_is_reported():
    client, _ = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(200, "<html>proxy error</html>"),
    ])
    with pytest.raises(QBitError) as excinfo:
        client.torrents_info()
    assert "invalid JSON" in str(excinfo.value)


def test_torrents_info_builds_filter_params():
    client, session = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(200, "[]", json_data=[{"name": "t"}]),
    ])
    assert client.torrents_info(status_filter="downloading") == [{"name": "t"}]
    assert session.calls[2][2]["params"] == {"filter": "downloading"}


def test_add_urls_and_files():
    client, session = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(200, "Ok."),
        FakeResponse(200, "Ok."),
    ])
    assert client.add_urls("magnet:?xt=urn:btih:1", savepath="/tank", category="radarr") is True
    assert session.calls[2][2]["data"] == {"urls": "magnet:?xt=urn:btih:1", "savepath": "/tank",
                                           "category": "radarr"}
    assert client.add_torrent_files(b"raw", "x.torrent", savepath="/tank") is True
    assert session.calls[3][2]["files"]["torrents"][0] == "x.torrent"
    assert session.calls[3][2]["files"]["torrents"][1] == b"raw"


def test_versions_are_fetched_once():
    client, session = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(200, "v5.1.0"),
        FakeResponse(200, "2.11.4"),
    ])
    assert client.fetch_versions() == ("v5.1.0", "2.11.4")
    assert client.fetch_versions() == ("v5.1.0", "2.11.4")
    assert len(session.calls) == 4


# --------------------------------------------------------------------------- #
# qBittorrent 4.x vs 5.x
# --------------------------------------------------------------------------- #
def test_modern_start_stop_is_preferred():
    client, session = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(200, ""),
    ])
    assert client.set_torrent_state(start=False) is True
    assert session.paths[-1] == "torrents/stop"


def test_legacy_pause_resume_fallback():
    client, session = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(404, "Not Found."),   # torrents/stop does not exist on 4.x
        FakeResponse(200, ""),             # torrents/pause does
    ])
    assert client.set_torrent_state(start=False) is True
    assert session.paths[-2:] == ["torrents/stop", "torrents/pause"]


def test_legacy_dialect_is_remembered():
    client, session = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(404, "Not Found."),
        FakeResponse(200, ""),
        FakeResponse(200, ""),
    ])
    client.set_torrent_state(start=True)
    client.set_torrent_state(start=True)
    assert session.paths[-1] == "torrents/resume"
    assert session.paths.count("torrents/start") == 1


def test_neither_dialect_available():
    client, _ = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(404, "Not Found."),
        FakeResponse(404, "Not Found."),
    ])
    with pytest.raises(QBitNotFoundError):
        client.set_torrent_state(start=True)


def test_conflict_is_reported_as_failure():
    client, _ = make_client([
        FakeResponse(403, "Forbidden."),
        FakeResponse(200, "Ok."),
        FakeResponse(409, "Conflict."),
    ])
    assert client.set_torrent_state(start=True) is False


# --------------------------------------------------------------------------- #
# Caching and back-off
# --------------------------------------------------------------------------- #
CFG = {"qbittorrent": {"host": "10.0.0.9", "port": "8080", "user": "admin", "pass": "pw"}}


def test_client_is_cached_per_credential_set():
    first = client_for(CFG)
    assert client_for(CFG) is first

    other = {"qbittorrent": dict(CFG["qbittorrent"], **{"pass": "other"})}
    assert client_for(other) is not first


def test_force_fresh_returns_a_new_client():
    first = client_for(CFG)
    assert client_for(CFG, force_fresh=True) is not first


def test_cache_is_bounded():
    for i in range(qbittorrent.MAX_CACHED_CLIENTS + 5):
        client_for({"qbittorrent": {"host": f"10.0.0.{i}", "port": "8080"}})
    assert qbittorrent.cached_client_count() <= qbittorrent.MAX_CACHED_CLIENTS


def test_rejected_login_backs_off_without_touching_the_network():
    session = FakeSession([FakeResponse(403, "Forbidden."), FakeResponse(200, "Fails.")])
    client = QBittorrentClient(cfg=CFG, session=session)

    with pytest.raises(QBitAuthError):
        client.login()
    assert qbittorrent.login_backoff_remaining(client.key) > 0

    # The next attempts must be answered from the back-off table: no socket is
    # opened, which is exactly what keeps qBittorrent from banning the bot.
    with patch("requests.Session") as session_cls:
        for _ in range(5):
            with pytest.raises(QBitAuthError) as excinfo:
                client_for(CFG).login()
            assert "will not retry" in str(excinfo.value)
        session_cls.return_value.request.assert_not_called()


def test_successful_login_clears_the_back_off():
    session = FakeSession([
        FakeResponse(403, "Forbidden."), FakeResponse(200, "Fails."),
        FakeResponse(403, "Forbidden."), FakeResponse(200, "Ok."),
    ])
    client = QBittorrentClient(cfg=CFG, session=session)

    with pytest.raises(QBitAuthError):
        client.login()
    assert qbittorrent.login_backoff_remaining(client.key) > 0

    assert client.login(force=True) is True
    assert qbittorrent.login_backoff_remaining(client.key) == 0


def test_clear_cache_drops_everything():
    client_for(CFG)
    assert qbittorrent.cached_client_count() == 1
    clear_client_cache()
    assert qbittorrent.cached_client_count() == 0


def test_get_configured_url():
    assert qbittorrent.get_configured_url(CFG) == "http://10.0.0.9:8080"
    assert qbittorrent.get_configured_url({"qbittorrent": {"host": ""}}) == ""
    assert qbittorrent.get_configured_url({}) == ""
