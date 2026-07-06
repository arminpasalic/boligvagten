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
import random
import re
import time
from datetime import datetime

from . import contact_cej, filters, notify, paths, sources

# Resolved once at import; tests monkeypatch these attributes directly.
CONFIG_FILE = paths.config_file()
EXAMPLE_FILE = paths.example_file()
STATE_FILE = paths.state_dir() / "seen_listings.json"


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
    # Import by path — cwd is not on sys.path when running as an installed command.
    spec = importlib.util.spec_from_file_location("boligvagten_config", CONFIG_FILE)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
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


# ---------- Seen-listing state ----------


def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(ids):
    STATE_FILE.write_text(json.dumps(sorted(ids), indent=2))


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


def notify_new(new_items, cfg):
    lines = [f"{len(new_items)} new listing(s):"]
    for it in new_items:
        lines.append(f"  • [{it.source}] {it.address} — {meta_line(it)}")
        lines.append(f"    {it.url}")
    message = "\n".join(lines)
    print(f"\n[{datetime.now().isoformat(timespec='seconds')}] {message}\n", flush=True)

    title = f"{len(new_items)} new apartment(s)"
    if getattr(cfg, "MACOS_NOTIFICATION", True):
        notify.send_macos(title, f"{len(new_items)} new. First: {new_items[0].address}")
    notify.send_ntfy(getattr(cfg, "NTFY", {}), title, message, click_url=new_items[0].url)
    run_actions(new_items, cfg)


def run_actions(new_items, cfg):
    """Optional follow-ups per source — currently the CEJ contact-form filler."""
    cc = getattr(cfg, "CEJ_CONTACT", None) or {}
    if cc.get("auto_contact"):
        for it in new_items:
            if it.source == "cej":
                try:
                    contact_cej.contact(it.url, cc)
                except Exception as e:
                    print(f"[cej] auto-contact error: {e}", flush=True)


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
        except Exception as e:
            print(f"[{stamp}] {mod.LABEL}: fetch failed — {e}", flush=True)
    return all_items, ok_count


def check_once(cfg):
    all_items, ok_count = fetch_enabled(cfg)
    if ok_count == 0:
        # Every source failed — assume offline; don't touch state.
        return None

    seen = load_seen()
    current = {it.id: it for it in all_items}
    new_ids = [i for i in current if i not in seen]

    stamp = datetime.now().isoformat(timespec="seconds")
    print(
        f"[{stamp}] Total: {len(current)} listings, {len(new_ids)} new, "
        f"{len(seen)} previously seen.",
        flush=True,
    )

    if new_ids and seen:
        notify_new([current[i] for i in new_ids], cfg)
    elif new_ids and not seen:
        print("First run — recording current listings as baseline (no alerts).", flush=True)

    save_seen(set(current.keys()) | seen)
    return len(new_ids)


# ---------- One-shot commands ----------


def list_once(cfg):
    """Fetch everything now, apply filters, print a table — a one-shot search."""
    rows, _ = fetch_enabled(cfg)
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
    lo = getattr(cfg, "POLL_MIN_SECONDS", 60)
    hi = getattr(cfg, "POLL_MAX_SECONDS", 180)
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
        description="Watch Danish rental sites and get an alert the minute a new listing appears.",
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
