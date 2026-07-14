"""State persistence, source registry, and first-run config bootstrap."""
import json
import types

import pytest

from boligvagten import monitor, sources

# ---------------------------------------------------------------- state

def test_seen_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "seen_listings.json")
    assert monitor.load_seen() == set()
    monitor.save_seen({"cej:b", "bp:1", "cej:a"})
    assert monitor.load_seen() == {"cej:a", "cej:b", "bp:1"}
    raw = json.loads((tmp_path / "seen_listings.json").read_text())
    assert raw["version"] == monitor.STATE_VERSION
    assert raw["initialized"] is True
    assert raw["seen"] == ["bp:1", "cej:a", "cej:b"]
    assert raw["actions"] == {}
    assert not list(tmp_path.glob(".seen_listings.json.*"))


def test_legacy_state_file_is_accepted(tmp_path, monkeypatch):
    state = tmp_path / "seen_listings.json"
    state.write_text('["bp:123", "kereby:x"]')
    monkeypatch.setattr(monitor, "STATE_FILE", state)
    assert monitor.load_seen() == {"bp:123", "kereby:x"}


def test_state_recovers_from_last_valid_backup(tmp_path, monkeypatch):
    state_file = tmp_path / "seen.json"
    monkeypatch.setattr(monitor, "STATE_FILE", state_file)
    monitor.save_seen({"x:first"})
    monitor.save_seen({"x:first", "x:second"})
    state_file.write_text("{truncated")

    # The backup is the prior complete generation, never the corrupt current file.
    assert monitor.load_seen() == {"x:first"}
    assert json.loads(state_file.read_text())["seen"] == ["x:first"]


def test_invalid_state_without_backup_stops_safely(tmp_path, monkeypatch):
    state_file = tmp_path / "seen.json"
    state_file.write_text("not json")
    monkeypatch.setattr(monitor, "STATE_FILE", state_file)
    with pytest.raises(RuntimeError, match="no usable backup"):
        monitor.load_state()


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


def test_notify_new_reports_required_channel_delivery(monkeypatch):
    item = _listing()
    monkeypatch.setattr(monitor.notify, "send_ntfy", lambda *args, **kwargs: False)
    enabled = types.SimpleNamespace(
        NTFY={"enabled": True, "topic": "x"}, MACOS_NOTIFICATION=False
    )
    disabled = types.SimpleNamespace(NTFY={"enabled": False}, MACOS_NOTIFICATION=False)
    assert monitor.notify_new([item], enabled) is False
    assert monitor.notify_new([item], disabled) is True


def test_check_once_deep_filters_new_listings(tmp_path, monkeypatch):
    """description_keywords gates the alert but never the seen-state."""
    cfg = types.SimpleNamespace(
        FILTERS={"description_keywords": ["altan"]}, SOURCES={},
    )
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "seen.json")
    notified = []
    def notify(items, _cfg):
        notified.append(items)
        return True

    monkeypatch.setattr(monitor, "notify_new", notify)

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


def test_notification_failure_retries_before_marking_seen(tmp_path, monkeypatch):
    cfg = types.SimpleNamespace(FILTERS={}, SOURCES={})
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "seen.json")
    batches = [
        [_listing(id="x:base")],
        [_listing(id="x:base"), _listing(id="x:new")],
        [_listing(id="x:base"), _listing(id="x:new")],
    ]
    monkeypatch.setattr(monitor, "fetch_enabled", lambda _cfg: (batches.pop(0), 1))
    outcomes = iter([False, True])
    attempts = []

    def notify(items, _cfg):
        attempts.append([item.id for item in items])
        return next(outcomes)

    monkeypatch.setattr(monitor, "notify_new", notify)
    monitor.check_once(cfg)  # baseline
    monitor.check_once(cfg)  # failed delivery
    assert "x:new" not in monitor.load_seen()
    monitor.check_once(cfg)  # successful retry
    assert "x:new" in monitor.load_seen()
    assert attempts == [["x:new"], ["x:new"]]


def test_empty_first_check_is_still_an_initialized_baseline(tmp_path, monkeypatch):
    cfg = types.SimpleNamespace(FILTERS={}, SOURCES={})
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "seen.json")
    batches = [[], [_listing(id="x:first")]]
    monkeypatch.setattr(monitor, "fetch_enabled", lambda _cfg: (batches.pop(0), 1))
    notified = []
    monkeypatch.setattr(
        monitor, "notify_new", lambda items, _cfg: notified.append(items) or True
    )

    assert monitor.check_once(cfg) == 0
    assert monitor.check_once(cfg) == 1
    assert [item.id for item in notified[0]] == ["x:first"]


def test_parser_health_failure_does_not_count_as_a_success(monkeypatch, capsys):
    class BrokenSource:
        KEY = "broken"
        LABEL = "Broken source"

        @staticmethod
        def fetch(_conf):
            raise sources.ParserHealthError("schema changed")

    monkeypatch.setattr(monitor.sources, "enabled", lambda _cfg: [(BrokenSource, {})])
    cfg = types.SimpleNamespace(FILTERS={}, SOURCES={})
    assert monitor.fetch_enabled(cfg) == ([], 0)
    assert "parser health check failed" in capsys.readouterr().out


def test_action_outbox_completes_and_interrupted_action_never_retries(tmp_path, monkeypatch):
    cfg = types.SimpleNamespace(CEJ_CONTACT={"auto_contact": True, "live_send": True})
    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "seen.json")
    calls = []
    monkeypatch.setattr(
        monitor.contact_cej, "contact", lambda url, _cc: calls.append(url) or True
    )
    state = monitor._empty_state()
    item = _listing(source="cej", id="cej:1", url="https://cej.example/1")
    monitor.queue_actions([item], cfg, state)
    monitor.save_state(state)
    monitor.process_action_outbox(cfg, state)
    assert calls == [item.url]
    assert state["actions"][item.id]["status"] == "completed"

    # Simulate termination after the durable claim but before a known result.
    state["actions"][item.id]["status"] = "in_progress"
    monitor.save_state(state)
    monitor.process_action_outbox(cfg, state)
    assert calls == [item.url]
    assert state["actions"][item.id]["status"] == "needs_review"


def test_default_poll_interval_is_30_to_60_seconds(monkeypatch):
    cfg = types.SimpleNamespace(SOURCES={}, FILTERS={})
    sampled = []
    monkeypatch.setattr(monitor, "check_once", lambda _cfg: 0)
    monkeypatch.setattr(
        monitor.random, "uniform", lambda low, high: sampled.append((low, high)) or low
    )
    monitor.run_loop(cfg, once=True)
    assert sampled == [(30, 60)]


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
