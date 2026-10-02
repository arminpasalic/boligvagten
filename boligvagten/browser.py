"""Playwright on demand — the headless browser that auto-contact drives.

Auto-contact is the one feature that needs more than the standard library.
When it is switched on, ensure() checks that Playwright imports and that a
headless Chromium actually launches. If not, it downloads both into a
temporary folder for this run only (Playwright via pip --target, Chromium's
headless shell via `playwright install`) and deletes that folder again when
the process exits. A computer that already has Playwright set up is used as
it is; nothing is downloaded.

Nothing here runs unless auto-contact is enabled for at least one site.
"""
import atexit
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TEMP_PREFIX = "boligvagten-browser-"
RETRY_AFTER_FAILURE = 600  # seconds before a failed download is tried again

_lock = threading.Lock()
_status = {"state": "unknown", "detail": ""}  # unknown/ready/missing/installing/failed
_temp_dir = None
_last_failure = 0.0
listeners = []  # callables run after every status change (the web UI pushes it)


def status():
    return dict(_status)


def _set(state, detail=""):
    _status.update(state=state, detail=detail)
    for listener in list(listeners):
        try:
            listener()
        except Exception:
            pass


def _check():
    """True when Playwright imports and a headless Chromium launches."""
    try:
        importlib.invalidate_caches()
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright is not installed"
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True, ""
    except Exception as e:
        first_line = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        return False, first_line


def ensure(allow_download=True, log=print):
    """Make the browser usable for this run. Returns True when it is ready."""
    global _last_failure
    with _lock:
        if _status["state"] == "ready":
            return True
        ok, detail = _check()
        if ok:
            _set("ready")
            return True
        if not allow_download:
            _set("missing", detail)
            return False
        if _status["state"] == "failed" and time.monotonic() - _last_failure < RETRY_AFTER_FAILURE:
            return False
        _set("installing", "Downloading a temporary browser for auto-contact")
        log("[browser] Auto-contact needs a headless browser; downloading a temporary "
            "copy for this run (about 150 MB download, 330 MB on disk; deleted when "
            "Boligvagten stops)...", flush=True)
        try:
            _install_temporary()
        except Exception as e:
            _last_failure = time.monotonic()
            _set("failed", str(e))
            log(f"[browser] download failed: {e}", flush=True)
            return False
        ok, detail = _check()
        if ok:
            _set("ready")
            log("[browser] ready.", flush=True)
            return True
        _last_failure = time.monotonic()
        _set("failed", detail)
        log(f"[browser] still not usable after download: {detail}", flush=True)
        return False


def _run(cmd, env):
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        raise RuntimeError(" / ".join(tail) or f"{cmd[0]} exited {result.returncode}")


def _install_temporary():
    global _temp_dir
    sweep_stale()
    if _temp_dir is None:
        _temp_dir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        (_temp_dir / "pid").write_text(str(os.getpid()))
        atexit.register(cleanup)
    lib = _temp_dir / "lib"
    browsers = _temp_dir / "browsers"
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(browsers))

    try:
        importlib.import_module("playwright")
    except ImportError:
        uv = os.environ.get("BOLIGVAGTEN_UV")  # set by the launcher's temporary runtime
        if uv and Path(uv).exists():
            cmd = [uv, "pip", "install", "--quiet", "--python", sys.executable,
                   "--target", str(lib), "playwright"]
        else:
            cmd = [sys.executable, "-m", "pip", "install", "--quiet",
                   "--disable-pip-version-check", "--target", str(lib), "playwright"]
        _run(cmd, env)
        sys.path.insert(0, str(lib))
        importlib.invalidate_caches()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(lib), env.get("PYTHONPATH")]))

    _run([sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"], env)
    # Later launches in this process must find the browser in the temp folder.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)


def cleanup():
    """Delete this run's temporary browser folder (registered with atexit)."""
    global _temp_dir
    if _temp_dir is not None:
        shutil.rmtree(_temp_dir, ignore_errors=True)
        _temp_dir = None


def _alive(pid, path):
    if sys.platform == "win32":
        # os.kill(pid, 0) is not a probe on Windows (it sends CTRL_C_EVENT).
        # Judge by age instead: a run's folder older than a day is stale.
        try:
            return time.time() - path.stat().st_mtime < 86400
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True  # exists but not ours, or can't tell: leave it alone
    return True


def sweep_stale():
    """Remove temp browser folders left behind by runs that were killed."""
    for path in Path(tempfile.gettempdir()).glob(f"{TEMP_PREFIX}*"):
        try:
            pid = int((path / "pid").read_text())
        except (OSError, ValueError):
            pid = None
        if pid is None or (pid != os.getpid() and not _alive(pid, path)):
            shutil.rmtree(path, ignore_errors=True)


def launch(playwright, headless=True):
    """Launch Chromium; fall back to headless when a visible window isn't available."""
    try:
        return playwright.chromium.launch(headless=headless)
    except Exception:
        if headless:
            raise
        return playwright.chromium.launch(headless=True)
