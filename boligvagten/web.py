"""Local web UI: settings, status and live log in the browser — `boligvagten --web`.

Standard library only. The server listens on 127.0.0.1 (random port), opens
the page in the default browser and runs the usual monitor loop in a
background thread. The page holds one Server-Sent Events connection open;
that connection doubles as the "is a tab still open?" signal. When no tab
has been connected for GRACE_SECONDS (long enough to survive a reload),
everything shuts down — closing the tab is how you stop boligvagten.

Every API call must carry the per-run token from the URL the browser was
opened with, and the Host header must name the loopback address, so other
websites and other local users' browsers can't drive or read the API.
"""
import hmac
import json
import secrets
import select
import socket
import sys
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlsplit

from . import __version__, browser, contact, monitor, notify, settings, sources

GRACE_SECONDS = 15           # no tab connected this long → shut down
FIRST_CONNECT_SECONDS = 60   # the browser gets this long to open the page at all
KEEPALIVE_SECONDS = 10
MAX_BODY_BYTES = 1_000_000

CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


# ---------- Log capture ----------


class LogBuffer:
    """The last N printed lines, numbered so a reconnecting page can resume."""

    def __init__(self, on_change, maxlen=500):
        self._lines = deque(maxlen=maxlen)
        self._partial = ""
        self._seq = 0
        self._lock = threading.Lock()
        self._on_change = on_change

    def feed(self, text):
        with self._lock:
            parts = (self._partial + text).split("\n")
            self._partial = parts.pop()
            for line in parts:
                self._seq += 1
                self._lines.append((self._seq, line))
            added = bool(parts)
        if added:
            self._on_change()

    def since(self, seq):
        with self._lock:
            return [(s, line) for s, line in self._lines if s > seq]


class Tee:
    """sys.stdout replacement: the terminal still gets everything, so does the page."""

    def __init__(self, stream, buffer):
        self._stream = stream
        self._buffer = buffer

    def write(self, text):
        self._buffer.feed(text)
        return self._stream.write(text)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


# ---------- Application state ----------


def _iso(ts):
    return ts.isoformat(timespec="seconds") if ts else None


class App:
    def __init__(self, data, grace=None, first_connect=None):
        self.lock = threading.Lock()
        self.changed = threading.Condition()
        self.stop = threading.Event()
        self.token = secrets.token_urlsafe(16)
        self.data = data
        self.grace = GRACE_SECONDS if grace is None else grace
        self.first_connect = FIRST_CONNECT_SECONDS if first_connect is None else first_connect
        self.clients = 0
        self.ever_connected = False
        self.idle_since = time.monotonic()
        self.rebaseline = False
        self.baseline_check = False  # the coming check only records a baseline
        self.status = {"last_check": None, "last_new": None, "online": None,
                       "next_check": None, "seen": 0,
                       "browser": browser.status(), "actions": []}
        self.testing = set()  # sites with a contact test running
        self.status_version = 0
        self.log = LogBuffer(self.notify)
        self.server = None

    # -- change notification for the SSE streams
    def notify(self):
        with self.changed:
            self.changed.notify_all()

    # -- config handed to the monitor
    def cfg(self):
        with self.lock:
            return settings.as_cfg(self.data)

    def watcher_cfg(self):
        """get_cfg for the watcher thread — also applies a pending re-baseline.

        Changing searches or filters would otherwise make every listing the
        new search returns look "new" and fire a burst of alerts. Resetting
        the state's `initialized` flag makes the next check record them
        silently, like a first run. Done here, in the watcher thread right
        before check_once, so it can't race the check's own state write.
        """
        with self.lock:
            rebaseline, self.rebaseline = self.rebaseline, False
        if rebaseline:
            state = monitor.load_state()
            state["initialized"] = False
            monitor.save_state(state)
            print("[web] Searches or filters changed — the next check records the "
                  "current listings without alerting.", flush=True)
        try:
            self.baseline_check = not monitor.load_state()["initialized"]
        except Exception:
            self.baseline_check = False
        return self.cfg()

    def on_cycle(self, result, delay):
        now = datetime.now()
        try:
            seen = len(monitor.load_state()["seen"])
        except Exception:
            seen = self.status["seen"]
        if result is not None and self.baseline_check:
            result = 0  # a baseline check records listings without alerting
        with self.lock:
            self.status.update(
                last_check=_iso(now),
                last_new=result,
                online=result is not None,
                next_check=_iso(now + timedelta(seconds=delay)),
                seen=seen,
            )
        self.refresh_contact()

    def refresh_contact(self):
        """Push the browser status and the latest contact attempts to the page."""
        try:
            actions = recent_actions(monitor.load_state()["actions"])
        except Exception:
            actions = self.status["actions"]
        with self.lock:
            self.status.update(browser=browser.status(), actions=actions)
            self.status_version += 1
        self.notify()

    def prepare_browser(self):
        """Download the browser in the background as soon as auto-contact is on."""
        if contact.any_enabled(contact.settings_from(self.cfg())):
            threading.Thread(target=browser.ensure, name="browser", daemon=True).start()

    def contact_test(self, site):
        """Dry-run the contact form on a current listing from one site."""
        cfg = self.cfg()
        module = next(m for m in sources.REGISTRY if m.KEY == site)
        conf = dict(cfg.SOURCES.get(site) or {})
        if not conf.get("enabled") or not conf.get("urls"):
            # A switched-off search may hold an unfinished address; any current
            # listing will do for a test, so use the template's search.
            default = settings.defaults()["SOURCES"][site]
            conf["urls"] = default.get("urls") or [default["url"]]
        with self.lock:
            if site in self.testing:
                return {"code": "busy", "detail": ""}
            self.testing.add(site)
        try:
            listings = module.fetch(conf)
            if not listings:
                return {"code": "no_listings", "detail": ""}
            cc = contact.settings_from(cfg)
            for it in listings[:5]:
                result = contact.run(site, it.url, it.id, cc, live=False)
                if result.code != contact.CLOSED:
                    break
            return {"code": result.code, "detail": result.detail, "url": it.url,
                    "address": it.address, "screenshot": result.code == contact.FILLED}
        finally:
            with self.lock:
                self.testing.discard(site)
            self.refresh_contact()

    def update_settings(self, incoming):
        with self.lock:
            current = self.data
        data = settings.validate(incoming)
        settings.save(data)
        with self.lock:
            searches_changed = (data["SOURCES"] != current["SOURCES"]
                                or data["FILTERS"] != current["FILTERS"])
            self.data = data
            self.rebaseline = self.rebaseline or searches_changed
        print("[web] Settings saved.", flush=True)
        self.prepare_browser()
        return data

    def new_topic(self):
        with self.lock:
            data = json.loads(json.dumps(self.data))
        data["NTFY"]["topic"] = notify.generate_topic()
        settings.save(data)
        with self.lock:
            self.data = data
        print(f"[web] New ntfy topic: {data['NTFY']['topic']}", flush=True)
        return data

    # -- tab presence
    def client_connected(self):
        with self.lock:
            self.clients += 1
            self.ever_connected = True

    def client_disconnected(self):
        with self.lock:
            self.clients -= 1
            if self.clients == 0:
                self.idle_since = time.monotonic()

    def should_exit(self):
        with self.lock:
            if self.clients:
                return False
            limit = self.grace if self.ever_connected else self.first_connect
            return time.monotonic() - self.idle_since > limit

    def shutdown(self, reason):
        if self.stop.is_set():
            return
        print(f"[web] {reason} Stopping.", flush=True)
        self.stop.set()
        self.notify()
        if self.server is not None:
            # server.shutdown() blocks until serve_forever returns — never call
            # it on the thread that might be serving this very request.
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def watchdog(self):
        while not self.stop.wait(0.5):
            if self.should_exit():
                self.shutdown("No browser tab is open.")


# ---------- HTTP ----------


def recent_actions(actions, limit=10):
    rows = []
    for listing_id, a in actions.items():
        rows.append({
            "listing": listing_id,
            "source": a.get("source"),
            "url": a.get("url"),
            "status": a.get("status"),
            "result": a.get("result"),
            "detail": a.get("detail") or a.get("error"),
            "live": bool(a.get("live_send")),
            "when": a.get("updated_at") or a.get("attempted_at") or a.get("queued_at"),
        })
    rows.sort(key=lambda r: r["when"] or "", reverse=True)
    return rows[:limit]


def _listing_row(it):
    return {
        "source": it.source,
        "address": it.address,
        "url": it.url,
        "deal": it.deal,
        "price_dkk": it.price_dkk,
        "rooms": it.rooms,
        "size_m2": it.size_m2,
        "monthly_fee_dkk": it.monthly_fee_dkk,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "boligvagten"
    sys_version = ""
    app = None  # set per server in make_server()

    def log_message(self, format, *args):  # noqa: A002 — keep the terminal clean
        pass

    # -- plumbing
    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _token_ok(self, query):
        given = self.headers.get("X-Token") or (query.get("t") or [""])[0]
        return hmac.compare_digest(given.encode(), self.app.token.encode())

    def _guard(self, query):
        if not self._host_ok():
            self._send(403, {"error": "bad_host"})
            return False
        if not self._token_ok(query):
            self._send(403, {"error": "bad_token"})
            return False
        return True

    def _json_body(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._send(415, {"error": "json_required"})
            return None
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._send(413, {"error": "too_large"})
            return None
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": "bad_json"})
            return None

    # -- routes
    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == "/":
            if not self._host_ok():
                self._send(403, {"error": "bad_host"})
                return
            page = resources.files("boligvagten").joinpath("web_ui.html").read_text("utf-8")
            self.send_response(200)
            data = page.encode("utf-8")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)
            return
        if not url.path.startswith("/api/"):
            self._send(404, {"error": "not_found"})
            return
        if not self._guard(query):
            return
        if url.path == "/api/state":
            self._send(200, self._state())
        elif url.path == "/api/events":
            self._events(query)
        elif url.path == "/api/contact-shot":
            self._screenshot(query)
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self):
        url = urlsplit(self.path)
        if not self._guard(parse_qs(url.query)):
            return
        body = self._json_body()
        if body is None:
            return
        app = self.app
        if url.path == "/api/settings":
            try:
                data = app.update_settings(body)
            except settings.SettingsError as e:
                self._send(400, {"error": e.code, "field": e.field})
                return
            self._send(200, {"settings": data})
        elif url.path == "/api/search":
            try:
                rows = monitor.collect_listings(app.cfg())
            except Exception as e:
                self._send(500, {"error": "search_failed", "detail": str(e)})
                return
            self._send(200, {"listings": [_listing_row(it) for it in rows]})
        elif url.path == "/api/test-notify":
            cfg = app.cfg()
            ok = notify.send_ntfy(
                cfg.NTFY, "Boligvagten test",
                "If you can read this on your phone, notifications work.",
                priority="default", tags="white_check_mark",
            )
            if cfg.MACOS_NOTIFICATION:
                notify.send_macos("Boligvagten test",
                                  "If you can see this, desktop notifications work.")
            self._send(200, {"ok": ok})
        elif url.path == "/api/contact-test":
            site = body.get("site")
            if site not in contact.SITES:
                self._send(400, {"error": "unknown_site"})
                return
            try:
                self._send(200, app.contact_test(site))
            except Exception as e:
                self._send(500, {"error": "test_failed", "detail": str(e)})
        elif url.path == "/api/new-topic":
            self._send(200, {"settings": app.new_topic()})
        elif url.path == "/api/stop":
            app.shutdown("Stop pressed.")  # non-blocking; this reply still goes out
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not_found"})

    def _state(self):
        app = self.app
        with app.lock:
            data = app.data
            status = dict(app.status)
        return {
            "version": __version__,
            "settings": data,
            "sources": [{"key": m.KEY, "label": m.LABEL} for m in sources.REGISTRY],
            "status": status,
            "subscribe_url": notify.subscribe_url(data["NTFY"]),
            "apps": {"ios": notify.NTFY_APP_IOS, "android": notify.NTFY_APP_ANDROID},
            "min_poll_seconds": settings.MIN_POLL_SECONDS,
            "contact": {
                "sites": [{"key": k, "label": contact.SITE_LABELS[k]} for k in contact.SITES],
                "hvem": contact.CEJ_HVEM,
                "beskaeftigelse": contact.CEJ_BESKAEFTIGELSE,
                "detaljer": contact.CEJ_DETALJER,
            },
        }

    def _screenshot(self, query):
        site = (query.get("site") or [""])[0]
        if site not in contact.SITES:
            self._send(404, {"error": "not_found"})
            return
        try:
            data = contact.screenshot_path(site).read_bytes()
        except OSError:
            self._send(404, {"error": "not_found"})
            return
        self._send(200, data, content_type="image/png")

    # -- Server-Sent Events: live log + status, and the tab-presence signal
    def _peer_closed(self):
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    def _event(self, name, payload, event_id=None):
        chunk = ""
        if event_id is not None:
            chunk += f"id: {event_id}\n"
        chunk += f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        self.wfile.write(chunk.encode("utf-8"))

    def _events(self, query):
        app = self.app
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        try:
            last_seq = int(self.headers.get("Last-Event-ID") or 0)
        except ValueError:
            last_seq = 0
        status_version = -1
        app.client_connected()
        try:
            last_write = 0.0
            while not app.stop.is_set():
                wrote = False
                for seq, line in app.log.since(last_seq):
                    self._event("log", line, event_id=seq)
                    last_seq = seq
                    wrote = True
                with app.lock:
                    version, status = app.status_version, dict(app.status)
                if version != status_version:
                    self._event("status", status)
                    status_version = version
                    wrote = True
                now = time.monotonic()
                if not wrote and now - last_write > KEEPALIVE_SECONDS:
                    self.wfile.write(b": keepalive\n\n")
                    wrote = True
                if wrote:
                    self.wfile.flush()
                    last_write = now
                if self._peer_closed():
                    return
                with app.changed:
                    app.changed.wait(1.0)
            self._event("stopped", {})
            self.wfile.flush()
        except OSError:
            pass  # tab closed mid-write (BrokenPipe / ConnectionReset)
        finally:
            app.client_disconnected()


def make_server(app, port=0):
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    app.server = server
    return server


# ---------- Entry point ----------


def serve(open_browser=True, port=0):
    """Run the web UI until the last tab closes (or Stop / Ctrl+C)."""
    monitor.STATE_FILE = settings.state_file()
    data = settings.load_or_seed()
    app = App(data)
    browser.listeners.append(app.refresh_contact)
    real_stdout = sys.stdout
    sys.stdout = Tee(real_stdout, app.log)
    server = make_server(app, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={app.token}"

    print(f"Boligvagten {__version__} — settings: {settings.settings_file()}", flush=True)
    print(f"Open in your browser: {url}", flush=True)
    print("Closing the browser tab stops boligvagten.", flush=True)

    watcher = threading.Thread(
        target=monitor.run_loop,
        args=(None,),
        kwargs={"stop": app.stop, "get_cfg": app.watcher_cfg, "on_cycle": app.on_cycle},
        name="watcher",
        daemon=True,
    )
    watcher.start()
    threading.Thread(target=app.watchdog, name="watchdog", daemon=True).start()
    app.refresh_contact()
    app.prepare_browser()
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass  # the URL is printed above

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        app.notify()
        server.server_close()
        watcher.join(timeout=10)  # let an in-flight check finish its state write
        sys.stdout = real_stdout
        browser.listeners.remove(app.refresh_contact)
        browser.cleanup()
        print("Boligvagten stopped.", flush=True)
