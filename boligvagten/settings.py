"""Settings for the web UI — the same values as config.py, stored as JSON.

config.py is a commented Python file meant for editing by hand; a browser
form can't rewrite it without destroying the comments. The web UI therefore
keeps its own settings.json in the per-user directory (paths.web_dir()).

The keys mirror config.py's module attributes, so as_cfg() hands the rest
of the code an object it already understands (everything reads config via
getattr). On first start the file is seeded from an existing config.py when
there is one, otherwise from config.example.py — the example stays the
single source of defaults.
"""
import copy
import importlib.util
import json
import re
import sys
import types
from urllib.parse import urlsplit

from . import contact, notify, paths, sources

KEYS = (
    "POLL_MIN_SECONDS",
    "POLL_MAX_SECONDS",
    "OFFLINE_MAX_BACKOFF",
    "FILTERS",
    "SOURCES",
    "NTFY",
    "MACOS_NOTIFICATION",
    "CONTACT",
)
FILTER_INT_KEYS = (
    "max_price_dkk",
    "min_price_dkk",
    "min_rooms",
    "max_rooms",
    "min_size_m2",
    "max_size_m2",
    "min_monthly_fee_dkk",
    "max_monthly_fee_dkk",
)
FILTER_LIST_KEYS = ("exclude_keywords", "include_keywords", "description_keywords")
SOURCE_KEYS = ("enabled", "urls", "filters", "max_pages")
NTFY_KEYS = ("enabled", "server", "topic")

# ntfy's own topic rule.
TOPIC_RE = re.compile(r"[-_A-Za-z0-9]{1,64}")

# Same politeness floor the README asks for: polling faster helps little and
# risks the sites' attention.
MIN_POLL_SECONDS = 30


class SettingsError(ValueError):
    """Invalid settings. `field` is a dotted path, `code` a stable error id."""

    def __init__(self, field, code):
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code


def settings_file():
    return paths.web_dir() / "settings.json"


def state_file():
    return paths.web_dir() / "seen_listings.json"


# ---------- Seeding ----------


def _import_config(path):
    """Import a config.py / config.example.py by path, without writing bytecode."""
    old_flag, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("boligvagten_seed_config", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old_flag
    return mod


def _from_module(mod):
    data = {k: copy.deepcopy(getattr(mod, k)) for k in KEYS if hasattr(mod, k)}
    if hasattr(mod, "CEJ_CONTACT"):  # pre-1.1 config.py
        data["CEJ_CONTACT"] = copy.deepcopy(mod.CEJ_CONTACT)
    return data


def defaults():
    return _from_module(_import_config(paths.example_file()))


def _normalize_filters(f):
    f = f or {}
    out = {k: f.get(k) for k in FILTER_INT_KEYS}
    out.update({k: list(f.get(k) or []) for k in FILTER_LIST_KEYS})
    return out


def _normalize_source(conf):
    conf = conf or {}
    out = {
        "enabled": bool(conf.get("enabled", bool(conf))),
        # One shape for the form: always a list, never the single "url".
        "urls": list(conf.get("urls") or ([conf["url"]] if conf.get("url") else [])),
        "filters": _normalize_filters(conf.get("filters")),
    }
    if conf.get("max_pages") is not None:
        out["max_pages"] = conf["max_pages"]
    return out


def normalize(data, base=None):
    """Fill gaps from the defaults and give every value the shape the form expects."""
    base = base if base is not None else defaults()
    out = {k: copy.deepcopy(data.get(k, base.get(k))) for k in KEYS}
    out["FILTERS"] = _normalize_filters(out["FILTERS"])
    src_in = out["SOURCES"] or {}
    out["SOURCES"] = {mod.KEY: _normalize_source(src_in.get(mod.KEY)) for mod in sources.REGISTRY}
    ntfy = dict(base.get("NTFY") or {})
    ntfy.update(out["NTFY"] or {})
    out["NTFY"] = {k: ntfy.get(k) for k in NTFY_KEYS}
    out["NTFY"]["topic"] = out["NTFY"]["topic"] or ""
    out["MACOS_NOTIFICATION"] = bool(out["MACOS_NOTIFICATION"])
    # An old settings.json / config.py may carry CEJ_CONTACT instead.
    out["CONTACT"] = contact.normalize(data.get("CONTACT"), data.get("CEJ_CONTACT"))
    return out


def load_or_seed():
    """Current settings; created on first start (from config.py or the example)."""
    f = settings_file()
    base = defaults()
    changed = False
    if f.exists():
        data = json.loads(f.read_text())
    else:
        existing = paths.config_file()
        data = _from_module(_import_config(existing)) if existing.exists() else base
        changed = True
    data = normalize(data, base)
    if data["NTFY"]["enabled"] and not data["NTFY"]["topic"]:
        data["NTFY"]["topic"] = notify.generate_topic()
        changed = True
    if changed:
        save(data)
    return data


def save(data):
    from .monitor import _atomic_write  # shared durable writer

    _atomic_write(settings_file(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def as_cfg(data):
    """The object monitor/check_once expects: attributes instead of keys."""
    return types.SimpleNamespace(**copy.deepcopy(data))


# ---------- Validation ----------


def _check_int(value, field, allow_none=True):
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsError(field, "not_a_number")
    if value < 0:
        raise SettingsError(field, "negative")


def _check_url(value, field):
    if not isinstance(value, str):
        raise SettingsError(field, "bad_url")
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SettingsError(field, "bad_url")


def _check_keys(d, allowed, field):
    if not isinstance(d, dict):
        raise SettingsError(field, "bad_type")
    for k in d:
        if k not in allowed:
            raise SettingsError(f"{field}.{k}" if field else k, "unknown_key")


def _check_filters(f, field):
    _check_keys(f, FILTER_INT_KEYS + FILTER_LIST_KEYS, field)
    for k in FILTER_INT_KEYS:
        _check_int(f.get(k), f"{field}.{k}")
    for lo, hi in (("min_price_dkk", "max_price_dkk"), ("min_rooms", "max_rooms"),
                   ("min_size_m2", "max_size_m2"),
                   ("min_monthly_fee_dkk", "max_monthly_fee_dkk")):
        if f.get(lo) is not None and f.get(hi) is not None and f[lo] > f[hi]:
            raise SettingsError(f"{field}.{lo}", "min_above_max")
    for k in FILTER_LIST_KEYS:
        words = f.get(k, [])
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise SettingsError(f"{field}.{k}", "bad_type")


def validate(data):
    """Raise SettingsError on the first problem; return the normalized settings."""
    _check_keys(data, KEYS, "")
    for k in ("POLL_MIN_SECONDS", "POLL_MAX_SECONDS", "OFFLINE_MAX_BACKOFF"):
        _check_int(data.get(k), k, allow_none=False)
    if data["POLL_MIN_SECONDS"] < MIN_POLL_SECONDS:
        raise SettingsError("POLL_MIN_SECONDS", "poll_too_fast")
    if data["POLL_MAX_SECONDS"] < data["POLL_MIN_SECONDS"]:
        raise SettingsError("POLL_MAX_SECONDS", "min_above_max")
    _check_filters(data.get("FILTERS") or {}, "FILTERS")

    known = {mod.KEY for mod in sources.REGISTRY}
    srcs = data.get("SOURCES") or {}
    if not isinstance(srcs, dict):
        raise SettingsError("SOURCES", "bad_type")
    for key, conf in srcs.items():
        field = f"SOURCES.{key}"
        if key not in known:
            raise SettingsError(field, "unknown_source")
        _check_keys(conf, SOURCE_KEYS, field)
        if not isinstance(conf.get("enabled", True), bool):
            raise SettingsError(f"{field}.enabled", "bad_type")
        urls = conf.get("urls", [])
        if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
            raise SettingsError(f"{field}.urls", "bad_type")
        # A switched-off source may hold a half-finished address; it is
        # checked again when the source is switched back on.
        if conf.get("enabled", True):
            if not urls:
                raise SettingsError(f"{field}.urls", "no_url")
            for url in urls:
                _check_url(url, f"{field}.urls")
        _check_filters(conf.get("filters") or {}, f"{field}.filters")
        if "max_pages" in conf:
            _check_int(conf["max_pages"], f"{field}.max_pages", allow_none=False)

    ntfy = data.get("NTFY") or {}
    _check_keys(ntfy, NTFY_KEYS, "NTFY")
    if not isinstance(ntfy.get("enabled", False), bool):
        raise SettingsError("NTFY.enabled", "bad_type")
    if ntfy.get("enabled"):
        _check_url(ntfy.get("server") or "", "NTFY.server")
        topic = ntfy.get("topic") or ""
        if not isinstance(topic, str) or not TOPIC_RE.fullmatch(topic):
            raise SettingsError("NTFY.topic", "bad_topic")
    if not isinstance(data.get("MACOS_NOTIFICATION", True), bool):
        raise SettingsError("MACOS_NOTIFICATION", "bad_type")
    _check_contact(data.get("CONTACT") or {})
    return normalize(data)


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _check_contact(c):
    _check_keys(c, contact.DETAIL_KEYS + ("sites", "headless"), "CONTACT")
    sites = c.get("sites") or {}
    _check_keys(sites, contact.SITES, "CONTACT.sites")
    for site, conf in sites.items():
        _check_keys(conf, ("auto_contact", "live_send"), f"CONTACT.sites.{site}")
        for k, v in conf.items():
            if not isinstance(v, bool):
                raise SettingsError(f"CONTACT.sites.{site}.{k}", "bad_type")
    for key in ("name", "email", "phone", "message", "birthdate", "hvem", "beskaeftigelse"):
        if not isinstance(c.get(key, ""), str):
            raise SettingsError(f"CONTACT.{key}", "bad_type")
    if c.get("birthdate") and not DATE_RE.fullmatch(c["birthdate"]):
        raise SettingsError("CONTACT.birthdate", "bad_date")
    if c.get("hvem") and c["hvem"] not in contact.CEJ_HVEM:
        raise SettingsError("CONTACT.hvem", "bad_choice")
    if c.get("beskaeftigelse") and c["beskaeftigelse"] not in contact.CEJ_BESKAEFTIGELSE:
        raise SettingsError("CONTACT.beskaeftigelse", "bad_choice")
    detaljer = c.get("detaljer", [])
    if not isinstance(detaljer, list) or any(d not in contact.CEJ_DETALJER for d in detaljer):
        raise SettingsError("CONTACT.detaljer", "bad_choice")
    # Sending for real needs real details, not the template's placeholders.
    normalized = contact.normalize(c)
    for site in contact.SITES:
        if contact.site_mode(normalized, site)[1]:
            missing = contact.missing_details(normalized, site)
            if missing:
                raise SettingsError(f"CONTACT.{missing[0]}", "needed_to_send")
