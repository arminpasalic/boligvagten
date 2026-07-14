#!/usr/bin/env python3
"""Boligvagten — watches Danish housing sites and alerts you the minute something new appears.

Quick start:      python3 monitor.py          (first run sets everything up)
One-shot search:  python3 monitor.py --list
All options:      python3 monitor.py --help

Installed via pip/uvx, the same entry point is the `boligvagten` command.
Configuration lives in config.py (created from config.example.py on first
run — see paths.py for where it is looked up). Sources live in sources/,
one module per site — see CONTRIBUTING.md for how to add your own.
"""
import argparse
import importlib.util
import json
import os
import random
import re
import sys
import tempfile
import time
from datetime import datetime

from . import contact_cej, filters, notify, paths, sources

# Resolved once at import; tests monkeypatch these attributes directly.
CONFIG_FILE = paths.config_file()
EXAMPLE_FILE = paths.example_file()
STATE_FILE = paths.state_dir() / "seen_listings.json"
STATE_VERSION = 2


# ---------- Config bootstrap ----------


def ensure_config():
    """First run: create config.py from the example, with a fresh ntfy topic."""
    if CONFIG_FILE.exists():
        return False
    text = EXAMPLE_FILE.read_text()
    text, n = re.subn(r'"topic":\s*""', f'"topic": "{notify.generate_topic()}"', text, count=1)
    if n != 1:
        print("warning: could not inject a generated ntfy topic — edit config.py", flush=True)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(text)
    print(f"Welcome! Created {CONFIG_FILE} from config.example.py — edit it to taste.", flush=True)
    return True


def load_config():
    created = ensure_config()
    # Import by path — cwd is not on sys.path when running as an installed
    # command. Skip bytecode so no __pycache__ appears next to the config.
    old_flag, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("boligvagten_config", CONFIG_FILE)
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
    finally:
        sys.dont_write_bytecode = old_flag
    return cfg, created


def ensure_topic(cfg):
    """Make sure NTFY has a topic; generate + persist one if it's empty."""
    n = getattr(cfg, "NTFY", {})
    if n.get("topic") or not n.get("enabled"):
        return n
    topic = notify.generate_topic()
    text = CONFIG_FILE.read_text()
    text, count = re.subn(r'"topic":\s*""', f'"topic": "{topic}"', text, count=1)
    if count == 1:
        CONFIG_FILE.write_text(text)
        n["topic"] = topic
        print(f"Generated a fresh ntfy topic and saved it to config.py: {topic}", flush=True)
    else:
        print("NTFY['topic'] is empty and could not be auto-set — edit config.py.", flush=True)
    return n


def run_onboarding(cfg):
    n = ensure_topic(cfg)
    if not n.get("enabled"):
        print("ntfy is disabled in config.py — no phone notifications.", flush=True)
        return
    sent = notify.send_ntfy(
        n,
        "Boligvagten is running",
        "Test notification — you're all set. New listings will appear here.",
        priority="default",
        tags="tada",
    )
    notify.print_onboarding(n, sent)


# ---------- Durable state ----------


def _empty_state():
    return {"version": STATE_VERSION, "initialized": False, "seen": set(), "actions": {}}


def _decode_state(raw):
    """Validate current state and migrate the legacy JSON-list format in memory."""
    if isinstance(raw, list):
        if not all(isinstance(item, str) for item in raw):
            raise ValueError("legacy state must contain only listing IDs")
        return {
            "version": STATE_VERSION,
            "initialized": True,
            "seen": set(raw),
            "actions": {},
        }
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        raise ValueError(f"unsupported state format (expected version {STATE_VERSION})")
    seen = raw.get("seen")
    actions = raw.get("actions")
    if not isinstance(seen, list) or not all(isinstance(item, str) for item in seen):
        raise ValueError("state 'seen' must be a list of listing IDs")
    if not isinstance(actions, dict) or not all(
        isinstance(key, str) and isinstance(value, dict) for key, value in actions.items()
    ):
        raise ValueError("state 'actions' must be an object")
    return {
        "version": STATE_VERSION,
        "initialized": bool(raw.get("initialized", True)),
        "seen": set(seen),
        "actions": actions,
    }


def _backup_file():
    return STATE_FILE.with_name(f"{STATE_FILE.name}.bak")


def load_state():
    """Load validated state, recovering from the last known-good backup if needed."""
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        return _decode_state(json.loads(STATE_FILE.read_text()))
    except (OSError, ValueError, json.JSONDecodeError) as current_error:
        backup = _backup_file()
        if backup.exists():
            try:
                recovered = _decode_state(json.loads(backup.read_text()))
                print(
                    f"[state] {STATE_FILE} is invalid ({current_error}); "
                    f"recovered from {backup}.",
                    flush=True,
                )
                save_state(recovered)
                return recovered
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        raise RuntimeError(
            f"state file is invalid and no usable backup exists: {STATE_FILE}: {current_error}"
        ) from current_error


def _atomic_write(path, text):
    """Write text durably, then atomically replace path on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
        # Persist the directory entry too where the platform permits it.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            pass
        else:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def save_state(state):
    """Atomically persist state and retain the previous valid generation as backup."""
    payload = {
        "version": STATE_VERSION,
        "initialized": bool(state.get("initialized")),
        "seen": sorted(state["seen"]),
        "actions": state["actions"],
    }
    if STATE_FILE.exists():
        previous = STATE_FILE.read_text()
        try:
            _decode_state(json.loads(previous))
        except (ValueError, json.JSONDecodeError):
            pass  # Never replace a good backup with corrupt state.
        else:
            _atomic_write(_backup_file(), previous)
    _atomic_write(STATE_FILE, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_seen():
    """Compatibility helper for callers that only need listing IDs."""
    return load_state()["seen"]


def save_seen(ids):
    """Compatibility helper that preserves the durable action outbox."""
    state = load_state()
    state["initialized"] = True
    state["seen"] = set(ids)
    save_state(state)


# ---------- New-listing handling ----------


def _kr(n):
    """Danish thousands separator: 3975000 → 3.975.000."""
    return f"{n:,}".replace(",", ".")


def meta_line(it):
    """rooms/size/price summary, aware of rent vs. for-sale listings."""
    rooms = it.rooms if it.rooms is not None else "?"
    size = it.size_m2 if it.size_m2 is not None else "?"
    if it.deal == "sale":
        price = f"{_kr(it.price_dkk)} DKK" if it.price_dkk is not None else "? DKK"
        extras = []
        if it.monthly_fee_dkk is not None:
            extras.append(f"ejerudgift {_kr(it.monthly_fee_dkk)} kr./md")
        if it.year_built is not None:
            extras.append(f"byggeår {it.year_built}")
        if extras:
            price += f" ({', '.join(extras)})"
    else:
        price = f"{_kr(it.price_dkk)} DKK/md" if it.price_dkk is not None else "? DKK/md"
    return f"{rooms}r, {size}m², {price}"


def notify_title(new_items):
    """Push title with the markets split: "2 nye lejeboliger, 1 til salg"."""
    n_rent = sum(1 for it in new_items if it.deal != "sale")
    n_sale = len(new_items) - n_rent
    parts = []
    if n_rent:
        parts.append("1 ny lejebolig" if n_rent == 1 else f"{n_rent} nye lejeboliger")
    if n_sale:
        parts.append(f"{n_sale} til salg" if n_rent else
                     ("1 ny bolig til salg" if n_sale == 1 else f"{n_sale} nye boliger til salg"))
    return ", ".join(parts)


def notify_new(new_items, cfg):
    """Send a batch and return whether its required notification channel accepted it."""
    lines = [f"{len(new_items)} new listing(s):"]
    for it in new_items:
        lines.append(f"  • [{it.source}] {it.address} — {meta_line(it)}")
        lines.append(f"    {it.url}")
    message = "\n".join(lines)
    print(f"\n[{datetime.now().isoformat(timespec='seconds')}] {message}\n", flush=True)

    title = notify_title(new_items)
    tags = ",".join(sorted({"moneybag" if it.deal == "sale" else "house" for it in new_items}))
    if getattr(cfg, "MACOS_NOTIFICATION", True):
        notify.send_macos(title, f"{len(new_items)} new. First: {new_items[0].address}")
    ntfy_cfg = getattr(cfg, "NTFY", {})
    if ntfy_cfg.get("enabled"):
        return notify.send_ntfy(
            ntfy_cfg, title, message, click_url=new_items[0].url, tags=tags
        )
    return True


def _now():
    return datetime.now().isoformat(timespec="seconds")


def queue_actions(new_items, cfg, state):
    """Add opt-in CEJ actions to the state transaction before listings are acknowledged."""
    cc = getattr(cfg, "CEJ_CONTACT", None) or {}
    if not cc.get("auto_contact"):
        return
    for it in new_items:
        if it.source == "cej" and it.id not in state["actions"]:
            state["actions"][it.id] = {
                "source": it.source,
                "url": it.url,
                "status": "pending",
                "live_send": bool(cc.get("live_send")),
                "queued_at": _now(),
            }


def process_action_outbox(cfg, state):
    """Run queued actions once; interrupted submissions require manual review."""
    cc = getattr(cfg, "CEJ_CONTACT", None) or {}
    changed = False
    for listing_id, action in state["actions"].items():
        if action.get("status") == "in_progress":
            action["status"] = "needs_review"
            action["updated_at"] = _now()
            changed = True
            print(
                f"[cej] {listing_id} was interrupted while auto-contact was running. "
                "It will NOT be retried automatically; inspect the CEJ inquiry and "
                f"the action entry in {STATE_FILE}.",
                flush=True,
            )
    if changed:
        save_state(state)

    if not cc.get("auto_contact"):
        return
    for listing_id, action in state["actions"].items():
        if action.get("status") != "pending":
            continue
        action["status"] = "in_progress"
        action["attempted_at"] = _now()
        save_state(state)  # Durable claim before opening/submitting the external form.
        action_cc = dict(cc)
        action_cc["live_send"] = bool(action.get("live_send"))
        try:
            succeeded = contact_cej.contact(action["url"], action_cc)
        except Exception as e:
            succeeded = False
            action["error"] = str(e)
            print(f"[cej] auto-contact error for {listing_id}: {e}", flush=True)
        action["status"] = "completed" if succeeded else "failed"
        action["updated_at"] = _now()
        save_state(state)


# ---------- Core check ----------


def fetch_enabled(cfg):
    """Fetch + filter every enabled source. Returns (listings, ok_count)."""
    global_filters = getattr(cfg, "FILTERS", None)
    stamp = datetime.now().isoformat(timespec="seconds")
    all_items, ok_count = [], 0
    for mod, conf in sources.enabled(getattr(cfg, "SOURCES", {})):
        try:
            items = mod.fetch(conf)
            kept = filters.apply(items, global_filters, conf.get("filters"))
            dropped = len(items) - len(kept)
            note = f" ({dropped} filtered out)" if dropped else ""
            print(f"[{stamp}] {mod.LABEL}: {len(kept)} listings{note}", flush=True)
            all_items.extend(kept)
            ok_count += 1
        except sources.ParserHealthError as e:
            print(f"[{stamp}] {mod.LABEL}: parser health check failed — {e}", flush=True)
        except Exception as e:
            print(f"[{stamp}] {mod.LABEL}: fetch failed — {e}", flush=True)
    return all_items, ok_count


def per_source_filters(cfg):
    return {mod.KEY: conf.get("filters") or {}
            for mod, conf in sources.enabled(getattr(cfg, "SOURCES", {}))}


def check_once(cfg):
    state = load_state()
    process_action_outbox(cfg, state)
    all_items, ok_count = fetch_enabled(cfg)
    if ok_count == 0:
        # Every source failed — assume offline; don't touch state.
        return None

    seen = state["seen"]
    current = {it.id: it for it in all_items}
    new_ids = [i for i in current if i not in seen]

    stamp = datetime.now().isoformat(timespec="seconds")
    print(
        f"[{stamp}] Total: {len(current)} listings, {len(new_ids)} new, "
        f"{len(seen)} previously seen.",
        flush=True,
    )

    if new_ids and state["initialized"]:
        # description_keywords runs here — only new listings, so a lazy page
        # fetch per listing stays cheap. Dropped ones still land in "seen".
        fresh = filters.deep_apply(
            [current[i] for i in new_ids],
            getattr(cfg, "FILTERS", None), per_source_filters(cfg),
        )
        fresh_ids = {it.id for it in fresh}
        # Deep-filter rejections are deliberately acknowledged; notification
        # failures are not, so those listings retry on the next poll.
        state["seen"].update(set(new_ids) - fresh_ids)
        if fresh and notify_new(fresh, cfg):
            queue_actions(fresh, cfg, state)
            state["seen"].update(fresh_ids)
        elif fresh:
            print(
                f"[notify] delivery failed; {len(fresh)} listing(s) remain pending "
                "and will retry on the next poll.",
                flush=True,
            )
    elif new_ids and not state["initialized"]:
        print("First run — recording current listings as baseline (no alerts).", flush=True)
        state["seen"].update(new_ids)

    state["initialized"] = True
    save_state(state)
    process_action_outbox(cfg, state)
    return len(new_ids)


# ---------- One-shot commands ----------


def list_once(cfg):
    """Fetch everything now, apply filters, print a table — a one-shot search."""
    rows, _ = fetch_enabled(cfg)
    rows = filters.deep_apply(rows, getattr(cfg, "FILTERS", None), per_source_filters(cfg))
    # Rentals first (cheapest up), then for-sale (cash prices would dwarf rents).
    rows.sort(key=lambda it: (it.deal != "rent", it.price_dkk is None, it.price_dkk or 0))
    if not rows:
        print("No listings matched your sources + filters.")
        return
    print()
    print(f"{'SOURCE':<14}{'PRICE':>13}  {'ROOMS':>5}  {'m²':>4}  ADDRESS")
    for it in rows:
        if it.price_dkk is None:
            price = "?"
        elif it.deal == "sale":
            price = _kr(it.price_dkk)
        else:
            price = f"{_kr(it.price_dkk)}/md"
        meta = f"{it.source:<14}{price:>13}  {it.rooms or '?':>5}  {it.size_m2 or '?':>4}"
        print(f"{meta}  {it.address}")
        print(f"{' ' * len(meta)}  {it.url}")
    print(f"\n{len(rows)} listing(s) right now.")


def test_notify(cfg):
    ok = notify.send_ntfy(
        getattr(cfg, "NTFY", {}),
        "Boligvagten test",
        "If you can read this on your phone, notifications work.",
        priority="default",
        tags="white_check_mark",
    )
    if getattr(cfg, "MACOS_NOTIFICATION", True):
        notify.send_macos("Boligvagten test", "If you can see this, desktop notifications work.")
    n = getattr(cfg, "NTFY", {})
    if ok:
        print(f"ntfy: sent to {notify.subscribe_url(n)}")
    elif n.get("enabled"):
        print("ntfy: sending failed (see error above).")
    else:
        print("ntfy: disabled in config.py.")


# ---------- Main loop ----------


def run_loop(cfg, once=False):
    lo = getattr(cfg, "POLL_MIN_SECONDS", 30)
    hi = getattr(cfg, "POLL_MAX_SECONDS", 60)
    if lo > hi:
        lo, hi = hi, lo
    offline_cap = getattr(cfg, "OFFLINE_MAX_BACKOFF", 600)
    enabled_labels = [mod.LABEL for mod, _ in sources.enabled(getattr(cfg, "SOURCES", {}))]
    print(
        f"Boligvagten starting. Poll: randomized {lo}-{hi}s. "
        f"Sources: {', '.join(enabled_labels) or 'NONE ENABLED'}. State: {STATE_FILE}",
        flush=True,
    )
    if filters.none_active(getattr(cfg, "FILTERS", None), getattr(cfg, "SOURCES", {})):
        print(
            "[note] No filters configured — every listing your source URLs return will "
            "alert. Fine if the URLs already encode your search; otherwise see FILTERS "
            "in config.py.",
            flush=True,
        )
    offline_streak = 0
    while True:
        got_any = False
        try:
            result = check_once(cfg)
            got_any = result is not None
        except Exception as e:
            print(f"[warn] check failed: {e}", flush=True)

        if got_any:
            if offline_streak:
                print("[ok] back online.", flush=True)
            offline_streak = 0
            delay = random.uniform(lo, hi)
        else:
            offline_streak += 1
            # Exponential backoff with jitter when every source fails — assume
            # we're offline and retry slowly so we don't hammer DNS/network.
            delay = min(offline_cap, hi * (2 ** min(offline_streak, 6)))
            delay = random.uniform(delay * 0.8, delay)
            print(
                f"[offline] all sources failed (streak={offline_streak}). "
                f"Backing off.",
                flush=True,
            )

        if once:
            break
        print(f"[sleep] next check in {delay:.1f}s", flush=True)
        time.sleep(delay)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="monitor.py",
        description="Watch Danish housing sites and get an alert when a new listing appears.",
    )
    ap.add_argument("--once", action="store_true",
                    help="run a single check and exit")
    ap.add_argument("--list", action="store_true",
                    help="fetch current listings, print them as a table, exit")
    ap.add_argument("--test-notify", action="store_true",
                    help="send a test notification to every channel and exit")
    ap.add_argument("--setup", action="store_true",
                    help="print the phone-notification setup again (sends a test push)")
    ap.add_argument("--contact-cej", metavar="URL",
                    help="fill the CEJ contact form for one listing URL and exit "
                         "(dry-run unless live_send is enabled in config.py)")
    args = ap.parse_args(argv)

    cfg, created = load_config()
    if created or args.setup:
        run_onboarding(cfg)
        if args.setup:
            return

    if args.contact_cej:
        contact_cej.contact(args.contact_cej, getattr(cfg, "CEJ_CONTACT", {}))
        return
    if args.test_notify:
        test_notify(cfg)
        return
    if args.list:
        list_once(cfg)
        return

    run_loop(cfg, once=args.once)


if __name__ == "__main__":
    main()
