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


def _contact_cfg(**sites):
    """A config with auto-contact on for the given sites: {site: live_send}."""
    return types.SimpleNamespace(CONTACT={
        "sites": {s: {"auto_contact": True, "live_send": live} for s, live in sites.items()},
        "name": "Ann", "email": "a@b.dk", "phone": "20304050", "message": "Hej",
        "birthdate": "1990-01-01",
    })


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    """Isolated state + a scripted contact.run; returns the list of calls."""
    from boligvagten import browser, contact

    monkeypatch.setattr(monitor, "STATE_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(browser, "ensure", lambda *a, **k: True)
    calls, results = [], []

    def fake_run(site, url, listing_id, cc, live, **kw):
        calls.append((site, listing_id, live))
        return results.pop(0) if results else contact.Result(contact.SENT, "ok")

    monkeypatch.setattr(contact, "run", fake_run)
    return calls, results


def _queued(cfg, *items):
    state = monitor._empty_state()
    monitor.queue_actions(list(items), cfg, state)
    monitor.save_state(state)
    return state


def test_action_outbox_completes_and_interrupted_action_never_retries(outbox):
    calls, _ = outbox
    cfg = _contact_cfg(cej=True)
    item = _listing(source="cej", id="cej:1", url="https://cej.example/1")
    state = _queued(cfg, item)
    monitor.process_action_outbox(cfg, state)
    assert calls == [("cej", "cej:1", True)]
    assert state["actions"][item.id]["status"] == "completed"

    # Simulate termination after the durable claim but before a known result.
    state["actions"][item.id]["status"] = "in_progress"
    monitor.save_state(state)
    monitor.process_action_outbox(cfg, state)
    assert len(calls) == 1
    assert state["actions"][item.id]["status"] == "needs_review"


def test_only_enabled_sites_get_actions(outbox):
    cfg = _contact_cfg(kereby=False)
    state = _queued(cfg, _listing(source="cej", id="cej:1"),
                    _listing(source="kereby", id="kereby:1"),
                    _listing(source="boligportal", id="bp:1"))
    assert set(state["actions"]) == {"kereby:1"}
    assert state["actions"]["kereby:1"]["live_send"] is False


def test_failures_before_sending_retry_then_give_up(outbox):
    from boligvagten import contact

    calls, results = outbox
    cfg = _contact_cfg(cej=True)
    state = _queued(cfg, _listing(source="cej", id="cej:1"))
    results.extend([contact.Result(contact.NOT_SENT, "form not found")] * 3)
    for _ in range(4):
        monitor.process_action_outbox(cfg, state)
    assert len(calls) == monitor.ACTION_MAX_ATTEMPTS
    action = state["actions"]["cej:1"]
    assert (action["status"], action["attempts"], action["result"]) == ("failed", 3, "not_sent")


def test_listing_page_not_ready_waits_without_spending_attempts(outbox):
    from boligvagten import contact

    calls, results = outbox
    cfg = _contact_cfg(kereby=True)
    state = _queued(cfg, _listing(source="kereby", id="kereby:1"))
    results.extend([contact.Result(contact.NOT_READY, "not published")] * 5)
    for _ in range(5):
        monitor.process_action_outbox(cfg, state)
    action = state["actions"]["kereby:1"]
    assert len(calls) == 5
    assert (action["status"], action.get("attempts")) == ("pending", 0)


def test_uncertain_send_is_never_retried(outbox):
    from boligvagten import contact

    calls, results = outbox
    cfg = _contact_cfg(cej=True)
    state = _queued(cfg, _listing(source="cej", id="cej:1"))
    results.append(contact.Result(contact.UNCERTAIN, "no reply"))
    monitor.process_action_outbox(cfg, state)
    monitor.process_action_outbox(cfg, state)
    assert len(calls) == 1
    assert state["actions"]["cej:1"]["status"] == "needs_review"


def test_switching_a_site_off_cancels_and_to_test_mode_stops_sending(outbox):
    calls, _ = outbox
    live_cfg = _contact_cfg(cej=True, kereby=True)
    state = _queued(live_cfg, _listing(source="cej", id="cej:1"),
                    _listing(source="kereby", id="kereby:1"))
    # Kereby switched off, CEJ switched from "send" to "test only" before the run.
    later_cfg = _contact_cfg(cej=False)
    monitor.process_action_outbox(later_cfg, state)
    assert state["actions"]["kereby:1"]["status"] == "cancelled"
    assert calls == [("cej", "cej:1", False)]


def test_stale_actions_expire(outbox):
    calls, _ = outbox
    cfg = _contact_cfg(cej=True)
    state = _queued(cfg, _listing(source="cej", id="cej:1"))
    state["actions"]["cej:1"]["queued_at"] = "2020-01-01T00:00:00"
    monitor.process_action_outbox(cfg, state)
    assert calls == []
    assert state["actions"]["cej:1"]["status"] == "expired"


def test_actions_wait_while_the_browser_is_unavailable(outbox, monkeypatch):
    from boligvagten import browser

    calls, _ = outbox
    monkeypatch.setattr(browser, "ensure", lambda *a, **k: False)
    cfg = _contact_cfg(cej=True)
    state = _queued(cfg, _listing(source="cej", id="cej:1"))
    monitor.process_action_outbox(cfg, state)
    assert calls == []
    assert state["actions"]["cej:1"]["status"] == "pending"


def test_legacy_cej_contact_config_still_works(outbox):
    calls, _ = outbox
    cfg = types.SimpleNamespace(CEJ_CONTACT={
        "auto_contact": True, "live_send": False, "name": "Ann", "email": "a@b.dk",
        "phone": "20304050", "message": "Hej",
    })
    state = _queued(cfg, _listing(source="cej", id="cej:1"))
    monitor.process_action_outbox(cfg, state)
    assert calls == [("cej", "cej:1", False)]


def test_default_poll_interval_is_30_to_60_seconds(monkeypatch):
    cfg = types.SimpleNamespace(SOURCES={}, FILTERS={})
    sampled = []
    monkeypatch.setattr(monitor, "check_once", lambda _cfg: 0)
    monkeypatch.setattr(
        monitor.random, "uniform", lambda low, high: sampled.append((low, high)) or low
    )
    monitor.run_loop(cfg, once=True)
    assert sampled == [(30, 60)]


def test_run_loop_stops_promptly_and_rereads_config(monkeypatch):
    import threading

    stop = threading.Event()
    seen_cfgs, cycles = [], []
    configs = iter([types.SimpleNamespace(SOURCES={}, POLL_MIN_SECONDS=30,
                                          POLL_MAX_SECONDS=60)] * 10)

    def check(cfg):
        seen_cfgs.append(cfg)
        return 0

    def on_cycle(result, delay):
        cycles.append((result, delay))
        if len(cycles) == 2:
            stop.set()

    monkeypatch.setattr(monitor, "check_once", check)
    # A real 30-60 s wait would hang the test; stop.wait() must return at once.
    monkeypatch.setattr(monitor.time, "sleep", lambda s: pytest.fail("used time.sleep"))
    waits = []
    real_wait = stop.wait
    monkeypatch.setattr(stop, "wait", lambda t: waits.append(t) or real_wait(0))

    monitor.run_loop(None, stop=stop, get_cfg=lambda: next(configs), on_cycle=on_cycle)
    assert len(seen_cfgs) == 2
    assert [r for r, _ in cycles] == [0, 0]
    assert len(waits) == 1 and 30 <= waits[0] <= 60


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
    # CONTACT carries every key the contact modules read...
    for key in ("sites", "headless", "name", "email", "phone", "message",
                "birthdate", "hvem", "beskaeftigelse", "detaljer"):
        assert key in cfg.CONTACT, f"CONTACT missing {key!r}"
    # ...covers every supported site, and ships with everything off.
    assert set(cfg.CONTACT["sites"]) == {"cej", "kereby"}
    for site in cfg.CONTACT["sites"].values():
        assert site == {"auto_contact": False, "live_send": False}


# ---------------------------------------------------------------- disclaimer

def _flat(text):
    return " ".join(text.split())


def test_disclaimer_is_shown_when_watching_starts(monkeypatch, capsys):
    from boligvagten import DISCLAIMER

    monkeypatch.setattr(monitor, "check_once", lambda _cfg: 0)
    monitor.run_loop(types.SimpleNamespace(SOURCES={}, FILTERS={}), once=True)
    assert DISCLAIMER in _flat(capsys.readouterr().out)


def test_disclaimer_is_shown_with_list_and_help(monkeypatch, capsys):
    from boligvagten import DISCLAIMER

    monkeypatch.setattr(monitor, "collect_listings", lambda _cfg: [])
    monitor.list_once(types.SimpleNamespace())
    assert DISCLAIMER in _flat(capsys.readouterr().out)
    with pytest.raises(SystemExit):
        monitor.main(["--help"])
    assert DISCLAIMER in _flat(capsys.readouterr().out)


def test_web_mode_ends_the_process_after_the_page_closes(monkeypatch):
    from boligvagten import web

    served = []
    monkeypatch.setattr(web, "serve", lambda: served.append(True))

    def fake_exit(code):
        raise SystemExit(f"os._exit({code})")

    monkeypatch.setattr(monitor.os, "_exit", fake_exit)
    with pytest.raises(SystemExit, match=r"os\._exit\(0\)"):
        monitor.main(["--web"])
    assert served == [True]
