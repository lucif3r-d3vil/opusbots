"""
End-to-end tests against a fake qBittorrent Web API server.

These reproduce the real world failure modes that used to be reported as a bare
"qBittorrent authentication failed. Check username and password.":

* a Radarr-style ``host`` + ``port`` pair (no ``http://`` scheme),
* qBittorrent's IP ban after five failed logins, caused by logging in once per
  API call,
* qBittorrent 5.x renaming ``torrents/pause|resume`` to ``torrents/stop|start``,
* authentication bypass for whitelisted subnets,
* a category that does not exist in qBittorrent.

The server itself lives in tests/fake_qbittorrent.py so it can also be started
standalone while working on the config panel.
"""

import pytest

from bots import torrent_handler
from shared import qbittorrent
from tests.fake_qbittorrent import FakeQBit, start_server, stop_server


@pytest.fixture()
def qbit_server():
    server = start_server()
    try:
        yield server
    finally:
        stop_server(server)


@pytest.fixture(autouse=True)
def clean_cache():
    qbittorrent.clear_client_cache()
    yield
    qbittorrent.clear_client_cache()


def cfg_for(server, host=None, port=None, user="admin", password="adminadmin", **extra):
    address = server.server_address
    qbit = {
        "host": host if host is not None else str(address[0]),
        "port": port if port is not None else str(address[1]),
        "user": user,
        "pass": password,
    }
    qbit.update(extra)
    return {"qbittorrent": qbit, "paths": {"downloads_completed": "/tank/Downloads/Completed"}}


def requests_to(server, needle):
    return [r for r in FakeQBit.state["requests"] if needle in r]


# --------------------------------------------------------------------------- #
# The reported bug: Radarr-style host/port, no scheme
# --------------------------------------------------------------------------- #
def test_radarr_style_host_and_port_authenticates(qbit_server):
    cfg = cfg_for(qbit_server)  # host="127.0.0.1", port="43210" -- no scheme anywhere
    torrents = torrent_handler.get_torrents(cfg)
    assert len(torrents) == 1
    assert torrents[0]["name"] == "Ubuntu 24.04 ISO"
    assert requests_to(qbit_server, "auth/login"), "should have logged in exactly through the API"


def test_scheme_less_host_with_inline_port_authenticates(qbit_server):
    port = qbit_server.server_address[1]
    cfg = cfg_for(qbit_server, host=f"127.0.0.1:{port}", port="")
    ok, message = torrent_handler.test_qbit_connection(cfg)
    assert ok is True
    assert "v5.1.0" in message


def test_full_url_host_still_works(qbit_server):
    port = qbit_server.server_address[1]
    cfg = cfg_for(qbit_server, host=f"http://127.0.0.1:{port}/", port="")
    assert torrent_handler.get_torrents(cfg)


def test_diagnose_reports_the_normalised_url(qbit_server):
    cfg = cfg_for(qbit_server)
    report = qbittorrent.diagnose(cfg)
    assert report["ok"] is True
    assert report["base_url"] == f"http://127.0.0.1:{qbit_server.server_address[1]}"
    assert report["version"] == "v5.1.0"
    assert report["api_version"] == "2.11.4"


# --------------------------------------------------------------------------- #
# Authentication failures are told apart, and never escalate into a ban
# --------------------------------------------------------------------------- #
def test_wrong_password_is_reported_as_credentials(qbit_server):
    cfg = cfg_for(qbit_server, password="nope")
    report = qbittorrent.diagnose(cfg)
    assert report["ok"] is False
    assert "username or password" in report["message"]
    assert "Fails" not in report["message"]


def test_bot_polling_does_not_trigger_an_ip_ban(qbit_server):
    """The old code logged in on *every* call; five failures banned the IP."""
    cfg = cfg_for(qbit_server, password="wrong")
    for _ in range(12):
        with pytest.raises(qbittorrent.QBitAuthError):
            torrent_handler.get_torrents(cfg)

    assert FakeQBit.state["fail_count"] < FakeQBit.state["ban_threshold"]
    assert FakeQBit.state["banned"] is False
    assert len(requests_to(qbit_server, "auth/login")) < FakeQBit.state["ban_threshold"]


def test_ban_is_explained(qbit_server):
    FakeQBit.state["banned"] = True
    cfg = cfg_for(qbit_server)
    report = qbittorrent.diagnose(cfg)
    assert report["ok"] is False
    assert "banned" in report["message"].lower()
    assert "Ban duration" in report["hint"] or "restart" in report["hint"].lower()


def test_ban_backoff_does_not_retry(qbit_server):
    FakeQBit.state["banned"] = True
    cfg = cfg_for(qbit_server)
    with pytest.raises(qbittorrent.QBitBannedError):
        torrent_handler.get_torrents(cfg)
    first = len(requests_to(qbit_server, "auth/login"))
    for _ in range(5):
        with pytest.raises(qbittorrent.QBitBannedError) as excinfo:
            torrent_handler.get_torrents(cfg)
        assert "will not retry" in str(excinfo.value)
    assert len(requests_to(qbit_server, "auth/login")) == first, "back-off must avoid extra logins"


def test_unreachable_host_is_a_connection_error(qbit_server):
    cfg = cfg_for(qbit_server, port="1")  # nothing listening there
    report = qbittorrent.diagnose(cfg)
    assert report["ok"] is False
    assert "Could not reach qBittorrent" in report["message"]
    assert "Radarr" in report["hint"]


def test_localhost_inside_docker_gets_a_hint(qbit_server):
    cfg = cfg_for(qbit_server, host="localhost", port="1")
    report = qbittorrent.diagnose(cfg)
    assert report["ok"] is False
    assert "bot container itself" in report["hint"]


def test_missing_host_is_reported(qbit_server):
    report = qbittorrent.diagnose({"qbittorrent": {"host": "", "port": ""}})
    assert report["ok"] is False
    assert "not configured" in report["message"].lower()


def test_wrong_path_reports_404_and_url_base_hint(qbit_server):
    cfg = cfg_for(qbit_server, url_base="/not-qbit")
    report = qbittorrent.diagnose(cfg)
    assert report["ok"] is False
    assert "404" in report["message"]
    assert "URL Base" in report["hint"]


# --------------------------------------------------------------------------- #
# Session reuse
# --------------------------------------------------------------------------- #
def test_login_happens_once_for_many_calls(qbit_server):
    cfg = cfg_for(qbit_server)
    for _ in range(6):
        assert torrent_handler.get_torrents(cfg)
    assert len(requests_to(qbit_server, "auth/login")) == 1


def test_auth_bypass_needs_no_login(qbit_server):
    FakeQBit.reset(bypass_auth=True)
    cfg = cfg_for(qbit_server, user="", password="")
    report = qbittorrent.diagnose(cfg)
    assert report["ok"] is True
    assert report["auth_bypassed"] is True
    assert not requests_to(qbit_server, "auth/login")


def test_stale_session_relogs_in_once(qbit_server):
    cfg = cfg_for(qbit_server)
    assert torrent_handler.get_torrents(cfg)
    FakeQBit.state["sessions"].clear()  # qBittorrent restarted / SID timed out
    assert torrent_handler.get_torrents(cfg)
    assert len(requests_to(qbit_server, "auth/login")) == 2


# --------------------------------------------------------------------------- #
# qBittorrent 4.x vs 5.x endpoint names
# --------------------------------------------------------------------------- #
def test_v5_uses_stop_and_start(qbit_server):
    cfg = cfg_for(qbit_server)  # api_version 2.11.4 -> qBittorrent 5.x
    assert torrent_handler.pause_torrents(cfg) is True
    assert torrent_handler.resume_torrents(cfg) is True
    assert requests_to(qbit_server, "torrents/stop")
    assert requests_to(qbit_server, "torrents/start")
    assert not requests_to(qbit_server, "torrents/pause")


def test_v4_falls_back_to_pause_and_resume(qbit_server):
    FakeQBit.reset(version="v4.6.5", api_version="2.9.3")
    cfg = cfg_for(qbit_server)
    assert torrent_handler.pause_torrents(cfg) is True
    assert torrent_handler.resume_torrents(cfg) is True
    assert requests_to(qbit_server, "torrents/pause")
    assert requests_to(qbit_server, "torrents/resume")


def test_v4_remembers_the_legacy_dialect(qbit_server):
    FakeQBit.reset(version="v4.6.5", api_version="2.9.3")
    cfg = cfg_for(qbit_server)
    torrent_handler.pause_torrents(cfg)
    before = len(FakeQBit.state["requests"])
    torrent_handler.pause_torrents(cfg)
    after = FakeQBit.state["requests"][before:]
    assert after == ["POST /api/v2/torrents/pause"], "no wasted 404 round trip the second time"


# --------------------------------------------------------------------------- #
# Adding torrents
# --------------------------------------------------------------------------- #
def test_add_magnet_ok(qbit_server):
    cfg = cfg_for(qbit_server)
    assert torrent_handler.add_magnet(cfg, "magnet:?xt=urn:btih:deadbeef", category="radarr") is True


def test_add_magnet_reports_connection_error(qbit_server):
    cfg = cfg_for(qbit_server, password="wrong")
    result = torrent_handler.add_torrent(cfg, "magnet:?xt=urn:btih:deadbeef", category="radarr")
    assert result["ok"] is False
    assert "username or password" in result["error"]


def test_unknown_category_falls_back_with_warning(qbit_server):
    cfg = cfg_for(qbit_server)
    result = torrent_handler.add_torrent(cfg, "magnet:?xt=urn:btih:deadbeef", category="does-not-exist")
    assert result["ok"] is True
    assert result["applied"] is False
    assert "does-not-exist" in result["warning"]


def test_state_helpers_cover_v4_and_v5_names():
    assert torrent_handler.is_active_state("downloading")
    assert torrent_handler.is_active_state("metaDL")
    assert torrent_handler.is_seeding_state("stalledUP")
    assert torrent_handler.is_stopped_state("pausedDL")   # qBittorrent 4.x
    assert torrent_handler.is_stopped_state("stoppedDL")  # qBittorrent 5.x
    assert not torrent_handler.is_stopped_state("downloading")


def test_active_ban_is_visible_without_new_requests(qbit_server):
    FakeQBit.state["banned"] = True
    cfg = cfg_for(qbit_server)
    with pytest.raises(qbittorrent.QBitBannedError):
        torrent_handler.get_torrents(cfg)

    assert qbittorrent.active_ban(cfg) > 0
    before = len(FakeQBit.state["requests"])
    # The web panel reports the ban from the back-off table instead of poking
    # qBittorrent again (which would restart the ban timer).
    report = qbittorrent.diagnose(cfg, force_fresh=not qbittorrent.active_ban(cfg))
    assert report["ok"] is False
    assert "banned" in report["message"].lower()
    assert len(FakeQBit.state["requests"]) == before
    assert qbittorrent.active_ban(cfg_for(qbit_server, password="someone-else")) == 0
