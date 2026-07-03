"""State persistence, source registry, and first-run config bootstrap."""
import json

import monitor
import sources

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
