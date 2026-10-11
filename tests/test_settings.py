"""Web-UI settings: seeding, normalization, validation, persistence."""
import json

import pytest

from boligvagten import settings, sources


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated per-user dir, and a cwd without any config.py."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("BOLIGVAGTEN_CONFIG", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return tmp_path


def test_seed_from_example_covers_every_source_and_generates_topic(home):
    data = settings.load_or_seed()
    assert set(data["SOURCES"]) == {mod.KEY for mod in sources.REGISTRY}
    assert data["NTFY"]["topic"].startswith("boligvagten-")
    # Single "url" entries become a one-item "urls" list for the form.
    assert all(isinstance(c["urls"], list) and c["urls"] for c in data["SOURCES"].values())
    assert settings.settings_file().exists()
    # Second start reads the file instead of re-seeding (topic is stable).
    assert settings.load_or_seed()["NTFY"]["topic"] == data["NTFY"]["topic"]


def test_seed_copies_an_existing_config_py(home):
    (home / "work" / "config.py").write_text(
        'POLL_MIN_SECONDS = 45\nPOLL_MAX_SECONDS = 90\n'
        'FILTERS = {"max_price_dkk": 12000, "exclude_keywords": ["studie"]}\n'
        'SOURCES = {"boligportal": {"enabled": True, "url": "https://example.dk/a"}}\n'
        'NTFY = {"enabled": True, "server": "https://ntfy.sh", "topic": "mytopic"}\n'
    )
    data = settings.load_or_seed()
    assert data["POLL_MIN_SECONDS"] == 45
    assert data["FILTERS"]["max_price_dkk"] == 12000
    assert data["FILTERS"]["exclude_keywords"] == ["studie"]
    assert data["SOURCES"]["boligportal"]["urls"] == ["https://example.dk/a"]
    assert data["SOURCES"]["cej"]["enabled"] is False  # absent in config.py → off
    assert data["NTFY"]["topic"] == "mytopic"


def test_saved_settings_round_trip_through_validate(home):
    data = settings.load_or_seed()
    data["FILTERS"]["min_rooms"] = 2
    data["SOURCES"]["kereby"]["enabled"] = False
    data = settings.validate(data)
    settings.save(data)
    assert json.loads(settings.settings_file().read_text()) == data
    cfg = settings.as_cfg(data)
    assert cfg.FILTERS["min_rooms"] == 2
    assert not list(settings.settings_file().parent.glob(".settings.json.*"))


@pytest.mark.parametrize(
    "mutate, field, code",
    [
        (lambda d: d["FILTERS"].update(max_price_dkk=-1), "FILTERS.max_price_dkk", "negative"),
        (lambda d: d["FILTERS"].update(min_rooms="2"), "FILTERS.min_rooms", "not_a_number"),
        (lambda d: d["FILTERS"].update(min_rooms=4, max_rooms=2),
         "FILTERS.min_rooms", "min_above_max"),
        (lambda d: d.update(POLL_MIN_SECONDS=5), "POLL_MIN_SECONDS", "poll_too_fast"),
        (lambda d: d.update(POLL_MAX_SECONDS=31, POLL_MIN_SECONDS=40),
         "POLL_MAX_SECONDS", "min_above_max"),
        (lambda d: d["SOURCES"]["cej"].update(urls=["javascript:alert(1)"]),
         "SOURCES.cej.urls", "bad_url"),
        (lambda d: d["SOURCES"]["cej"].update(urls=[]), "SOURCES.cej.urls", "no_url"),
        (lambda d: d["SOURCES"].update(nosuchsite={"enabled": True}),
         "SOURCES.nosuchsite", "unknown_source"),
        (lambda d: d.update(EVIL=1), "EVIL", "unknown_key"),
        (lambda d: d["NTFY"].update(topic="has space"), "NTFY.topic", "bad_topic"),
        (lambda d: d["SOURCES"]["sdk"].update(min_interval_hours="daily"),
         "SOURCES.sdk.min_interval_hours", "not_a_number"),
        (lambda d: d["SOURCES"]["sdk"].update(private_kitchen_bath="yes"),
         "SOURCES.sdk.private_kitchen_bath", "bad_type"),
        (lambda d: d["SOURCES"]["heimstaden"].update(unit_types="Studiebolig"),
         "SOURCES.heimstaden.unit_types", "bad_type"),
    ],
)
def test_validate_rejects_bad_values(home, mutate, field, code):
    data = settings.load_or_seed()
    mutate(data)
    with pytest.raises(settings.SettingsError) as exc:
        settings.validate(data)
    assert (exc.value.field, exc.value.code) == (field, code)


def test_sdk_options_survive_a_save_from_the_page(home):
    data = settings.load_or_seed()
    assert data["SOURCES"]["sdk"]["min_interval_hours"] == 24   # from config.example.py
    assert data["SOURCES"]["sdk"]["use_global_filters"] is False
    data["SOURCES"]["sdk"].update(enabled=True, private_kitchen_bath=True)
    out = settings.validate(data)
    assert out["SOURCES"]["sdk"]["min_interval_hours"] == 24
    assert out["SOURCES"]["sdk"]["private_kitchen_bath"] is True


def test_heimstaden_unit_lists_survive_a_save_from_the_page(home):
    data = settings.load_or_seed()
    conf = data["SOURCES"]["heimstaden"]
    assert conf["unit_types"] == ["Studiebolig", "Ungdomsbolig"]   # from config.example.py
    conf.update(enabled=True, unit_types=[], properties=["Domus Vista"])
    out = settings.validate(data)["SOURCES"]["heimstaden"]
    assert (out["unit_types"], out["properties"]) == ([], ["Domus Vista"])


def test_source_added_after_settings_were_saved_gets_example_defaults_switched_off(home):
    data = settings.load_or_seed()
    del data["SOURCES"]["sdk"]                   # a settings.json from before sdk existed
    settings.save(data)
    sdk = settings.load_or_seed()["SOURCES"]["sdk"]
    assert sdk["enabled"] is False
    assert sdk["urls"] and sdk["min_interval_hours"] == 24


def test_disabled_source_may_have_no_or_unfinished_url(home):
    data = settings.load_or_seed()
    data["SOURCES"]["cej"].update(enabled=False, urls=[])
    data["SOURCES"]["kereby"].update(enabled=False, urls=["work in progress"])
    out = settings.validate(data)
    assert out["SOURCES"]["cej"]["urls"] == []
    assert out["SOURCES"]["kereby"]["urls"] == ["work in progress"]
