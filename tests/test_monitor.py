"""State persistence, source registry, and first-run config bootstrap."""
import json

from boligvagten import monitor, sources

# ---------------------------------------------------------------- state

def test_seen_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "seen_listings.json")
    assert monitor.load_seen() == set()
    monitor.save_seen({"cej:b", "bp:1", "cej:a"})
    assert monitor.load_seen() == {"cej:a", "cej:b", "bp:1"}
    # File format stays a sorted JSON list — compatible with pre-refactor state.
    assert json.loads((tmp_path / "seen_listings.json").read_text()) == [
        "bp:1", "cej:a", "cej:b",
    ]


def test_legacy_state_file_is_accepted(tmp_path, monkeypatch):
    state = tmp_path / "seen_listings.json"
    state.write_text('["bp:123", "kereby:x"]')
    monkeypatch.setattr(monitor, "STATE_FILE", state)
    assert monitor.load_seen() == {"bp:123", "kereby:x"}


# ---------------------------------------------------------------- formatting

def _listing(**kw):
    from boligvagten.sources.base import Listing
    base = dict(source="x", id="x:1", name="n", address="Gade 1", rooms=3,
                size_m2=86, price_dkk=17200, url="https://x.dk/1")
    base.update(kw)
    return Listing(**base)


def test_meta_line_rent_formatting():
    assert monitor.meta_line(_listing()) == "3r, 86m², 17.200 DKK/md"
    assert monitor.meta_line(
        _listing(rooms=None, size_m2=None, price_dkk=None)
    ) == "?r, ?m², ? DKK/md"


def test_meta_line_sale_formatting():
    it = _listing(deal="sale", price_dkk=3_975_000, monthly_fee_dkk=3645, year_built=1936)
    assert monitor.meta_line(it) == (
        "3r, 86m², 3.975.000 DKK (ejerudgift 3.645 kr./md, byggeår 1936)"
    )
    # Extras are dropped when unknown, not printed as '?'.
    bare = _listing(deal="sale", price_dkk=2_500_000)
    assert monitor.meta_line(bare) == "3r, 86m², 2.500.000 DKK"


def test_notify_title_splits_markets():
    rent, sale = _listing(), _listing(deal="sale")
    assert monitor.notify_title([rent]) == "1 ny lejebolig"
    assert monitor.notify_title([rent, rent]) == "2 nye lejeboliger"
    assert monitor.notify_title([sale]) == "1 ny bolig til salg"
    assert monitor.notify_title([rent, rent, sale]) == "2 nye lejeboliger, 1 til salg"


def test_check_once_deep_filters_new_listings(tmp_path, monkeypatch):
    """description_keywords gates the alert but never the seen-state."""
    import types

    cfg = types.SimpleNamespace(
        FILTERS={"description_keywords": ["altan"]}, SOURCES={},
    )
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "seen.json")
    notified = []
    monkeypatch.setattr(monitor, "notify_new", lambda items, _cfg: notified.append(items))

    batches = [
        [_listing(id="x:base", description="baseline")],
        [_listing(id="x:base", description="baseline"),
         _listing(id="x:plain", description="ingen udenomsplads")],
        [_listing(id="x:base", description="baseline"),
         _listing(id="x:plain", description="ingen udenomsplads"),
         _listing(id="x:hit", description="skøn altan mod vest")],
    ]
    monkeypatch.setattr(monitor, "fetch_enabled", lambda _cfg: (batches.pop(0), 1))

    assert monitor.check_once(cfg) == 1   # baseline run — no alert
    assert monitor.check_once(cfg) == 1   # new but keyword-less — silenced
    assert notified == []
    assert monitor.check_once(cfg) == 1   # keyword match — alert fires
    assert [it.id for it in notified[0]] == ["x:hit"]
    # The silenced listing is still remembered — it must never re-alert.
    assert "x:plain" in monitor.load_seen()


# ---------------------------------------------------------------- registry

def test_registry_enabled_selection():
    cfg = {
        "cej": {"enabled": True, "url": "u"},
        "cityapartment": {"enabled": False, "url": "u"},
        "boligportal": {"url": "u"},  # no "enabled" key → on by default
        # kereby missing entirely → off
    }
    keys = [mod.KEY for mod, _ in sources.enabled(cfg)]
    assert keys == ["cej", "boligportal"]


def test_registry_modules_have_required_interface():
    for mod in sources.REGISTRY:
        assert isinstance(mod.KEY, str) and mod.KEY
        assert isinstance(mod.LABEL, str) and mod.LABEL
        assert callable(mod.parse)
        assert callable(mod.fetch)


# ---------------------------------------------------------------- first run

def test_ensure_config_creates_config_with_generated_topic(tmp_path, monkeypatch):
    example = tmp_path / "config.example.py"
    example.write_text(
        'NTFY = {\n    "enabled": True,\n    "topic": "",  # auto-generated\n}\n'
    )
    monkeypatch.setattr(monitor, "EXAMPLE_FILE", example)
    monkeypatch.setattr(monitor, "CONFIG_FILE", tmp_path / "config.py")

    assert monitor.ensure_config() is True
    text = (tmp_path / "config.py").read_text()
    assert '"topic": ""' not in text
    assert '"topic": "boligvagten-' in text
    assert "# auto-generated" in text  # surrounding comment survives

    # Second call must not overwrite the user's config.
    assert monitor.ensure_config() is False


def test_shipped_example_config_has_injectable_topic_placeholder():
    # Guards the config.example.py ↔ ensure_config() regex contract.
    text = (monitor.EXAMPLE_FILE).read_text()
    assert text.count('"topic": ""') == 1


def _load_example_config():
    import importlib.util

    spec = importlib.util.spec_from_file_location("config_example", monitor.EXAMPLE_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_example_config_is_complete_and_safe():
    cfg = _load_example_config()
    # Every registered source has a config entry with a fetchable URL.
    for mod in sources.REGISTRY:
        conf = cfg.SOURCES[mod.KEY]
        assert conf.get("url") or conf.get("urls")
    # CEJ_CONTACT carries every key contact_cej.contact() reads...
    for key in ("auto_contact", "live_send", "headless", "name", "email", "phone",
                "message", "birthdate", "hvem", "beskaeftigelse", "detaljer"):
        assert key in cfg.CEJ_CONTACT, f"CEJ_CONTACT missing {key!r}"
    # ...and ships with both safety switches off.
    assert cfg.CEJ_CONTACT["auto_contact"] is False
    assert cfg.CEJ_CONTACT["live_send"] is False
