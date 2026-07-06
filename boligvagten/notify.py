"""Notification channels (console, macOS banner, ntfy push) and ntfy onboarding.

ntfy (https://ntfy.sh) is a free pub/sub push service: POST text to
https://ntfy.sh/<topic> and every phone subscribed to <topic> gets a push.
No account needed — the topic name is the only secret, so it must be
unguessable. generate_topic() takes care of that on first run.
"""
import secrets
import subprocess
import sys
import urllib.request

NTFY_APP_IOS = "https://apps.apple.com/app/ntfy/id1625396347"
NTFY_APP_ANDROID = "https://play.google.com/store/apps/details?id=io.heckel.ntfy"

# Unambiguous letters/digits only (no 0/O, 1/l) — you may have to type this on a phone.
_TOPIC_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_topic():
    suffix = "".join(secrets.choice(_TOPIC_ALPHABET) for _ in range(10))
    return f"boligvagten-{suffix}"


def subscribe_url(ntfy_cfg):
    server = ntfy_cfg.get("server", "https://ntfy.sh").rstrip("/")
    return f"{server}/{ntfy_cfg.get('topic', '')}"


def send_ntfy(ntfy_cfg, title, body, click_url=None, priority="high", tags="house"):
    """POST one push message. Returns True when accepted by the server."""
    if not ntfy_cfg.get("enabled") or not ntfy_cfg.get("topic"):
        return False
    # HTTP headers must be latin-1 safe; strip non-ASCII from the short title
    # (the body is UTF-8 and keeps æøå just fine).
    safe_title = title.encode("ascii", "replace").decode("ascii")
    headers = {"Title": safe_title, "Priority": priority, "Tags": tags}
    if click_url:
        headers["Click"] = click_url
    req = urllib.request.Request(
        subscribe_url(ntfy_cfg),
        data=body.encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print(f"(ntfy failed: {e})", flush=True)
        return False


def send_macos(title, body):
    """Desktop banner via osascript. No-op outside macOS."""
    if sys.platform != "darwin":
        return
    body = body.replace('"', "'")
    script = f'display notification "{body}" with title "{title}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception as e:
        print(f"(macOS notification failed: {e})", flush=True)


def print_onboarding(ntfy_cfg, test_sent):
    topic = ntfy_cfg.get("topic", "")
    line = "=" * 64
    test_note = (
        "A test notification was just sent — it appears once you subscribe\n"
        "     (ntfy.sh keeps messages for ~12 hours)."
        if test_sent else
        "Sending a test notification failed — check your connection,\n"
        "     then run:  python3 monitor.py --test-notify"
    )
    print(f"""
{line}
  Get alerts on your phone (takes ~2 minutes)
{line}
  Your private alert channel:

      {subscribe_url(ntfy_cfg)}

  1. Install the free ntfy app:
       iPhone:  {NTFY_APP_IOS}
       Android: {NTFY_APP_ANDROID}
  2. In the app: tap + and subscribe to the topic:

      {topic}

  3. {test_note}

  No phone handy? The channel URL above also works in any browser.
  Keep the topic secret — anyone who knows it can read your alerts.
  It is saved in config.py under NTFY["topic"].
{line}
""", flush=True)
