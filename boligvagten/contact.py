"""Auto-contact: fill in a landlord's contact form the moment a listing appears.

Popular listings collect hundreds of inquiries within hours, so answering in
the first minutes is what gets you a viewing. Supported sites each have a
module (contact_cej, contact_kereby) that drives the site's own form in a
headless browser; this module holds what they share:

* settings — the CONTACT dict in config.py / the web UI: your details plus
  a per-site on/off ("auto_contact") and send switch ("live_send");
* results — what happened, which decides whether a retry is safe;
* run() — opens the browser and enforces the dry-run guarantee.

Dry runs (live_send off) fill the form and save a screenshot. While they
run, every non-GET request to the site is blocked except the ones a site
module explicitly allows (cookie consent), so a dry run cannot submit
anything even if a click lands on the wrong button.
"""
import copy
import re
from collections import namedtuple
from urllib.parse import urlsplit

from . import browser

# What a contact attempt ended with.
SENT = "sent"            # the site confirmed the message
FILLED = "filled"        # dry run: form filled, screenshot saved, nothing sent
CLOSED = "closed"        # the listing no longer takes inquiries
NOT_SENT = "not_sent"    # failed before anything was submitted: safe to retry
NOT_READY = "not_ready"  # listing page not available yet: retry, no attempt counted
UNCERTAIN = "uncertain"  # Send was pressed but no confirmation: never retried

Result = namedtuple("Result", "code detail")

SITES = ("cej", "kereby")
SITE_LABELS = {"cej": "CEJ Udlejning", "kereby": "Kereby"}

# CEJ's profile step offers these tiles (labels as shown on the site).
CEJ_HVEM = ("Enkeltperson", "Par/kærester", "Familie", "Gruppe/roomies")
CEJ_BESKAEFTIGELSE = ("I arbejde", "Studerende", "Ledig", "Pensioneret")
CEJ_DETALJER = ("Har hjemmeboende børn", "Har kæledyr", "Søger delebolig", "Søger parkering")

DETAIL_KEYS = ("name", "email", "phone", "message",
               "birthdate", "hvem", "beskaeftigelse", "detaljer")
EXAMPLE_VALUES = {"name": "Your Name", "email": "you@example.com", "phone": "12345678"}
PLACEHOLDER_RE = re.compile(r"<[a-zæøå]+>", re.I)  # "<navn>", "<telefon>", ...

DEFAULTS = {
    "sites": {site: {"auto_contact": False, "live_send": False} for site in SITES},
    "headless": True,
    "name": "",
    "email": "",
    "phone": "",
    "message": "",
    "birthdate": "",
    "hvem": "Enkeltperson",
    "beskaeftigelse": "I arbejde",
    "detaljer": [],
}


# ---------- Settings ----------


def normalize(contact=None, legacy_cej=None):
    """One CONTACT dict from the new key, the old CEJ_CONTACT, or nothing."""
    out = copy.deepcopy(DEFAULTS)
    if contact:
        for key in DETAIL_KEYS + ("headless",):
            if key in contact and contact[key] is not None:
                out[key] = copy.deepcopy(contact[key])
        for site, conf in (contact.get("sites") or {}).items():
            if site in out["sites"] and isinstance(conf, dict):
                out["sites"][site] = {
                    "auto_contact": bool(conf.get("auto_contact")),
                    "live_send": bool(conf.get("live_send")),
                }
    elif legacy_cej:
        # Pre-1.1 configs: CEJ_CONTACT held both the details and CEJ's switches.
        for key in DETAIL_KEYS + ("headless",):
            if key in legacy_cej and legacy_cej[key] is not None:
                out[key] = copy.deepcopy(legacy_cej[key])
        out["sites"]["cej"] = {
            "auto_contact": bool(legacy_cej.get("auto_contact")),
            "live_send": bool(legacy_cej.get("live_send")),
        }
    out["detaljer"] = list(out["detaljer"] or [])
    out["headless"] = bool(out["headless"])
    return out


def settings_from(cfg):
    """The normalized CONTACT settings of a loaded config (module or namespace)."""
    return normalize(getattr(cfg, "CONTACT", None), getattr(cfg, "CEJ_CONTACT", None))


def site_mode(contact_cfg, site):
    """(auto_contact, live_send) for one site."""
    conf = contact_cfg["sites"].get(site) or {}
    auto = bool(conf.get("auto_contact"))
    return auto, auto and bool(conf.get("live_send"))


def any_enabled(contact_cfg):
    return any(site_mode(contact_cfg, s)[0] for s in SITES)


def missing_details(contact_cfg, site):
    """Fields that must be filled in before a real message may be sent."""
    needed = ["name", "email", "phone", "message"]
    if site == "cej":
        needed.append("birthdate")
    missing = []
    for key in needed:
        value = (contact_cfg.get(key) or "").strip()
        if not value or value == EXAMPLE_VALUES.get(key) or PLACEHOLDER_RE.search(value):
            missing.append(key)
    return missing


def screenshot_path(site):
    """Next to the active state file (config dir for the CLI, web dir for --web)."""
    from . import monitor  # late import: monitor imports this module

    return monitor.STATE_FILE.parent / f"contact_{site}.png"


def module_for(site):
    if site == "cej":
        from . import contact_cej
        return contact_cej
    if site == "kereby":
        from . import contact_kereby
        return contact_kereby
    raise KeyError(site)


def site_for_url(url):
    host = urlsplit(url).hostname or ""
    if host.endswith("cej.dk"):
        return "cej"
    if host.endswith("kereby.dk") or host.endswith("kerebyudlejning.dk"):
        return "kereby"
    return None


# ---------- Running ----------


def _dry_run_guard(module):
    """Route handler: block every non-GET to the site unless the module allows it."""
    def guard(route, request):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return route.continue_()
        host = urlsplit(request.url).hostname or ""
        if not module.owns_host(host):
            return route.abort()  # analytics and other third parties: not needed
        if module.allow_in_dry_run(request):
            return route.continue_()
        print(f"[contact] dry run blocked {request.method} {request.url}", flush=True)
        return route.abort()
    return guard


def run(site, listing_url, listing_id, contact_cfg, live, screenshot=None, route=None):
    """Contact one listing. Never raises; returns a Result.

    route: optional Playwright route handler installed instead of the
    dry-run guard (used by scripts/check_contact.py to fake a server reply).
    """
    module = module_for(site)
    if live:
        missing = missing_details(contact_cfg, site)
        if missing:
            return Result(NOT_SENT, f"fill in your details first: {', '.join(missing)}")
    if not browser.ensure():
        return Result(NOT_SENT, f"browser not available: {browser.status()['detail']}")
    shot = screenshot or screenshot_path(site)
    mode = "LIVE" if live else "dry run"
    print(f"[{site}] contacting {listing_url} ({mode})", flush=True)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            chromium = browser.launch(p, headless=contact_cfg.get("headless", True))
            try:
                ctx = chromium.new_context(
                    viewport={"width": 1280, "height": 900}, locale="da-DK"
                )
                if route is not None:
                    ctx.route("**/*", route)
                elif not live:
                    ctx.route("**/*", _dry_run_guard(module))
                page = ctx.new_page()
                page.set_default_timeout(15000)
                result = module.contact(page, listing_url, listing_id, contact_cfg, live, shot)
            finally:
                chromium.close()
    except Exception as e:
        # Site modules turn anything after the Send click into UNCERTAIN
        # themselves; an exception reaching here happened before that.
        result = Result(NOT_SENT, f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")
    print(f"[{site}] {result.code}: {result.detail}", flush=True)
    return result
