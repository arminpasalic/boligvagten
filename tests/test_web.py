"""Web UI server: access control, API round-trips, and stop-when-tab-closes."""
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from boligvagten import monitor, settings, web
from boligvagten.sources.base import Listing


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("BOLIGVAGTEN_CONFIG", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "xdg" / "seen.json")
    return tmp_path


@pytest.fixture
def running(home):
    app = web.App(settings.load_or_seed(), grace=0.3, first_connect=30)
    server = web.make_server(app)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    port = server.server_address[1]
    yield app, port
    app.stop.set()
    server.shutdown()
    server.server_close()
    thread.join(5)


def call(port, path, body=None, token=None, host=None, content_type="application/json"):
    headers = {}
    if token is not None:
        headers["X-Token"] = token
    if host is not None:
        headers["Host"] = host
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = content_type
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def open_events(port, token):
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(f"GET /api/events?t={token} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
    assert s.recv(15).startswith(b"HTTP/1.0 200")
    return s


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------- access control

def test_api_requires_the_token(running):
    app, port = running
    assert call(port, "/api/state")[0] == 403
    assert call(port, "/api/state", token="wrong")[0] == 403
    assert call(port, "/api/state", token=app.token)[0] == 200


def test_api_rejects_foreign_host_header(running):
    # A DNS-rebinding page would send its own hostname.
    app, port = running
    status, body = call(port, "/api/state", token=app.token, host=f"evil.example:{port}")
    assert (status, body["error"]) == (403, "bad_host")


def test_post_requires_json_content_type(running):
    app, port = running
    status, body = call(port, "/api/settings", body={}, token=app.token,
                        content_type="text/plain")
    assert (status, body["error"]) == (415, "json_required")


def test_page_is_served_with_csp(running):
    _, port = running
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        assert resp.status == 200
        assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
        assert b"<title>Boligvagten</title>" in resp.read()


# ---------------------------------------------------------------- API

def test_state_lists_sources_and_settings(running):
    app, port = running
    status, body = call(port, "/api/state", token=app.token)
    assert status == 200
    assert [s["key"] for s in body["sources"]][-1] == "boligsiden"
    assert body["subscribe_url"].endswith(body["settings"]["NTFY"]["topic"])


def test_settings_save_updates_config_and_requests_rebaseline(running, monkeypatch):
    app, port = running
    data = call(port, "/api/state", token=app.token)[1]["settings"]
    data["FILTERS"]["max_price_dkk"] = 15000
    data["CONTACT"]["sites"]["kereby"]["auto_contact"] = True
    monkeypatch.setattr(web.browser, "ensure", lambda *a, **k: True)
    status, body = call(port, "/api/settings", body=data, token=app.token)
    assert status == 200
    assert app.cfg().FILTERS["max_price_dkk"] == 15000
    assert app.cfg().CONTACT["sites"]["kereby"] == {"auto_contact": True, "live_send": False}
    assert json.loads(settings.settings_file().read_text())["FILTERS"]["max_price_dkk"] == 15000

    # The watcher applies the pending re-baseline before its next check.
    monitor.save_seen({"x:1"})
    assert monitor.load_state()["initialized"] is True
    app.watcher_cfg()
    assert monitor.load_state()["initialized"] is False
    assert monitor.load_seen() == {"x:1"}


def test_invalid_settings_report_field_and_code(running):
    app, port = running
    data = call(port, "/api/state", token=app.token)[1]["settings"]
    data["POLL_MIN_SECONDS"] = 1
    status, body = call(port, "/api/settings", body=data, token=app.token)
    assert (status, body) == (400, {"error": "poll_too_fast", "field": "POLL_MIN_SECONDS"})


def test_search_returns_rows(running, monkeypatch):
    app, port = running
    row = Listing(source="x", id="x:1", name="n", address="Gade 1", rooms=2,
                  size_m2=50, price_dkk=9000, url="https://x.dk/1")
    monkeypatch.setattr(monitor, "fetch_enabled", lambda cfg: ([row], 1))
    status, body = call(port, "/api/search", body={}, token=app.token)
    assert status == 200
    assert body["listings"][0]["address"] == "Gade 1"
    assert body["listings"][0]["price_dkk"] == 9000


def test_new_topic_is_saved(running):
    app, port = running
    old = app.cfg().NTFY["topic"]
    status, body = call(port, "/api/new-topic", body={}, token=app.token)
    assert status == 200
    assert body["settings"]["NTFY"]["topic"] != old
    assert json.loads(settings.settings_file().read_text())["NTFY"]["topic"] != old


def test_stop_endpoint_shuts_down(running):
    app, port = running
    assert call(port, "/api/stop", body={}, token=app.token)[0] == 200
    assert app.stop.is_set()


# ---------------------------------------------------------------- lifecycle

def test_closing_the_last_tab_stops_after_grace(running):
    app, port = running
    threading.Thread(target=app.watchdog, daemon=True).start()
    tab = open_events(port, app.token)
    time.sleep(0.6)  # longer than the grace period: an open tab keeps it alive
    assert not app.stop.is_set()
    tab.close()
    assert wait_for(app.stop.is_set)


def test_reload_within_grace_keeps_running(running):
    app, port = running
    app.grace = 1.0
    threading.Thread(target=app.watchdog, daemon=True).start()
    first = open_events(port, app.token)
    first.close()
    time.sleep(0.2)
    second = open_events(port, app.token)
    time.sleep(1.2)
    assert not app.stop.is_set()
    second.close()


def test_events_stream_log_and_status(running):
    app, port = running
    tab = open_events(port, app.token)
    tab.settimeout(5)
    app.log.feed("hello from the watcher\n")
    app.on_cycle(3, 42)
    received = b""
    while b"hello from the watcher" not in received or b'"last_new": 3' not in received:
        chunk = tab.recv(4096)
        assert chunk, "stream ended early"
        received += chunk
    tab.close()


def test_serve_runs_until_the_tab_closes(home, monkeypatch):
    monkeypatch.setattr(web, "GRACE_SECONDS", 0.3)
    opened = []
    monkeypatch.setattr(web.webbrowser, "open", opened.append)
    monkeypatch.setattr(monitor, "check_once", lambda cfg: 0)
    thread = threading.Thread(target=web.serve, daemon=True)
    thread.start()
    assert wait_for(lambda: opened)
    url = opened[0]
    port = int(url.split(":")[2].split("/")[0])
    token = url.split("?t=")[1]
    tab = open_events(port, token)
    tab.close()
    thread.join(10)
    assert not thread.is_alive()
    assert settings.settings_file().exists()


# ---------------------------------------------------------------- auto-contact

def test_contact_test_runs_a_dry_run_on_a_current_listing(running, monkeypatch):
    from boligvagten import contact
    from boligvagten.sources import cej

    app, port = running
    rows = [Listing(source="cej", id="cej:1", name="n", address="Closed 1", rooms=2,
                    size_m2=50, price_dkk=9000, url="https://udlejning.cej.dk/boliger/1"),
            Listing(source="cej", id="cej:2", name="n", address="Open 2", rooms=2,
                    size_m2=50, price_dkk=9000, url="https://udlejning.cej.dk/boliger/2")]
    monkeypatch.setattr(cej, "fetch", lambda conf: rows)
    calls = []

    def fake_run(site, url, listing_id, cc, live, **kw):
        calls.append((listing_id, live))
        code = contact.CLOSED if listing_id == "cej:1" else contact.FILLED
        contact.screenshot_path(site).write_bytes(b"\x89PNG fake")
        return contact.Result(code, "x")

    monkeypatch.setattr(contact, "run", fake_run)
    status, body = call(port, "/api/contact-test", body={"site": "cej"}, token=app.token)
    assert status == 200
    assert (body["code"], body["address"], body["screenshot"]) == ("filled", "Open 2", True)
    assert calls == [("cej:1", False), ("cej:2", False)]  # never live, skips closed

    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/contact-shot?site=cej&t={app.token}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.headers["Content-Type"] == "image/png"
        assert resp.read() == b"\x89PNG fake"


def test_contact_test_rejects_unknown_sites_and_needs_the_token(running):
    app, port = running
    assert call(port, "/api/contact-test", body={"site": "boligportal"},
                token=app.token)[0] == 400
    assert call(port, "/api/contact-test", body={"site": "cej"})[0] == 403
    assert call(port, f"/api/contact-shot?site=../../etc&t={app.token}")[0] == 404


def test_state_reports_browser_status_and_recent_actions(running, monkeypatch):
    from boligvagten import browser

    app, port = running
    state = monitor._empty_state()
    state["actions"]["kereby:1"] = {"source": "kereby", "url": "https://kereby.dk/bolig/a/",
                                    "status": "completed", "result": "sent",
                                    "updated_at": "2026-10-02T12:00:00"}
    monitor.save_state(state)
    monkeypatch.setattr(browser, "_status", {"state": "installing", "detail": ""})
    app.refresh_contact()
    status = call(port, "/api/state", token=app.token)[1]["status"]
    assert status["browser"]["state"] == "installing"
    assert status["actions"][0]["listing"] == "kereby:1"
    assert status["actions"][0]["result"] == "sent"


def test_page_shows_the_disclaimer():
    from importlib import resources

    from boligvagten import DISCLAIMER

    page = resources.files("boligvagten").joinpath("web_ui.html").read_text("utf-8")
    assert 'data-i18n="disclaimer"' in page
    assert f'disclaimer: "{DISCLAIMER}"' in page  # English text matches word for word
