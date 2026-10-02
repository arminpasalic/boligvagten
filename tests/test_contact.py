"""Auto-contact settings, safety rules and the dry-run request guard (offline)."""
import types

from boligvagten import contact, contact_cej, contact_kereby, settings


def test_legacy_cej_contact_becomes_contact_settings():
    cc = contact.normalize(None, {
        "auto_contact": True, "live_send": True, "headless": False,
        "name": "Ann", "email": "a@b.dk", "phone": "20304050", "message": "Hej",
        "birthdate": "1990-01-01", "hvem": "Familie", "beskaeftigelse": "Ledig",
        "detaljer": ["Har kæledyr"],
    })
    assert cc["sites"]["cej"] == {"auto_contact": True, "live_send": True}
    assert cc["sites"]["kereby"] == {"auto_contact": False, "live_send": False}
    assert (cc["name"], cc["hvem"], cc["detaljer"], cc["headless"]) == (
        "Ann", "Familie", ["Har kæledyr"], False)


def test_new_contact_key_wins_over_legacy():
    cfg = types.SimpleNamespace(
        CONTACT={"sites": {"kereby": {"auto_contact": True}}, "name": "New"},
        CEJ_CONTACT={"auto_contact": True, "name": "Old"},
    )
    cc = contact.settings_from(cfg)
    assert cc["name"] == "New"
    assert contact.site_mode(cc, "cej") == (False, False)
    assert contact.site_mode(cc, "kereby") == (True, False)


def test_live_send_needs_auto_contact():
    cc = contact.normalize({"sites": {"cej": {"auto_contact": False, "live_send": True}}})
    assert contact.site_mode(cc, "cej") == (False, False)


def test_template_placeholders_and_examples_block_sending():
    cc = contact.normalize({
        "name": "Your Name", "email": "a@b.dk", "phone": "20304050",
        "message": "Hej, jeg hedder <navn>.", "birthdate": "",
    })
    assert contact.missing_details(cc, "cej") == ["name", "message", "birthdate"]
    assert contact.missing_details(cc, "kereby") == ["name", "message"]
    result = contact.run("kereby", "https://kereby.dk/bolig/x/", "kereby:1", cc, live=True)
    assert result.code == contact.NOT_SENT
    assert "fill in your details" in result.detail


def test_settings_refuse_sending_with_template_details(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    data = settings.load_or_seed()  # seeded from config.example.py: placeholders
    data["CONTACT"]["sites"]["cej"] = {"auto_contact": True, "live_send": False}
    settings.validate(data)  # test mode is fine with the template
    data["CONTACT"]["sites"]["cej"]["live_send"] = True
    try:
        settings.validate(data)
    except settings.SettingsError as e:
        assert (e.field, e.code) == ("CONTACT.name", "needed_to_send")
    else:
        raise AssertionError("sending with the template's details must be refused")


def test_site_detection_from_urls():
    assert contact.site_for_url("https://udlejning.cej.dk/boliger/abc") == "cej"
    assert contact.site_for_url("https://kereby.dk/bolig/x/") == "kereby"
    assert contact.site_for_url("https://www.boligportal.dk/x") is None


# ---------------------------------------------------------------- dry-run guard

class FakeRoute:
    def __init__(self):
        self.outcome = None

    def continue_(self):
        self.outcome = "continued"

    def abort(self):
        self.outcome = "aborted"


def _request(method, url, body=None):
    return types.SimpleNamespace(method=method, url=url, post_data=body)


def _guarded(module, method, url, body=None):
    route = FakeRoute()
    contact._dry_run_guard(module)(route, _request(method, url, body))
    return route.outcome


def test_dry_run_guard_blocks_every_submission():
    cej_submit = "https://udlejning.cej.dk/kontakt?_data=routes%2Fcontact"
    assert contact_cej.is_submit(_request("POST", cej_submit))
    assert _guarded(contact_cej, "POST", cej_submit, "message=hi") == "aborted"
    kereby_submit = "https://kereby.dk/wp-json/jorato-templates/v1/contact"
    assert contact_kereby.is_submit(_request("POST", kereby_submit))
    assert _guarded(contact_kereby, "POST", kereby_submit, "{}") == "aborted"
    # Any other write to the site is blocked too, as is third-party tracking.
    assert _guarded(contact_cej, "PUT", "https://udlejning.cej.dk/anything") == "aborted"
    assert _guarded(contact_cej, "POST", "https://www.google.com/ccm/collect") == "aborted"


def test_dry_run_guard_allows_pages_and_cej_cookie_consent():
    assert _guarded(contact_cej, "GET", "https://udlejning.cej.dk/boliger/abc") == "continued"
    consent = "https://udlejning.cej.dk/?index=&_data=routes%2Fhome%2Froute"
    assert _guarded(contact_cej, "POST", consent, "marketingAccepted=true") == "continued"
    # Same endpoint with anything else in the body is not consent.
    assert _guarded(contact_cej, "POST", consent, "message=hi") == "aborted"


def test_sweep_removes_only_folders_of_dead_runs(tmp_path, monkeypatch):
    import os
    import sys

    import pytest

    from boligvagten import browser

    if sys.platform == "win32":
        pytest.skip("Windows judges stale folders by age")
    monkeypatch.setattr(browser.tempfile, "gettempdir", lambda: str(tmp_path))
    mine = tmp_path / f"{browser.TEMP_PREFIX}mine"
    dead = tmp_path / f"{browser.TEMP_PREFIX}dead"
    other = tmp_path / "unrelated"
    for d in (mine, dead, other):
        d.mkdir()
    (mine / "pid").write_text(str(os.getpid()))
    (dead / "pid").write_text("999999")  # no such process
    browser.sweep_stale()
    assert mine.exists() and other.exists()
    assert not dead.exists()
