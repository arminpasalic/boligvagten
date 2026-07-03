"""Notification plumbing — all offline (network is monkeypatched away)."""
import urllib.request

import notify


def test_generate_topic_format_and_uniqueness():
    topics = {notify.generate_topic() for _ in range(50)}
    assert len(topics) == 50  # effectively unguessable, definitely unique
    for t in topics:
        prefix, suffix = t.rsplit("-", 1)
        assert prefix == "boligvagten"
        assert len(suffix) == 10
        assert set(suffix) <= set(notify._TOPIC_ALPHABET)


def test_subscribe_url_joins_server_and_topic():
    assert notify.subscribe_url(
        {"server": "https://ntfy.sh/", "topic": "abc"}
    ) == "https://ntfy.sh/abc"
    # Server defaults to ntfy.sh when omitted.
    assert notify.subscribe_url({"topic": "abc"}) == "https://ntfy.sh/abc"


def test_send_ntfy_short_circuits_without_network(monkeypatch):
    def boom(*a, **kw):  # any network call would fail the test
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert notify.send_ntfy({"enabled": False, "topic": "t"}, "x", "y") is False
    assert notify.send_ntfy({"enabled": True, "topic": ""}, "x", "y") is False


def test_send_ntfy_builds_latin1_safe_request(monkeypatch):
    captured = {}

    class FakeResponse:
        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ok = notify.send_ntfy(
        {"enabled": True, "server": "https://ntfy.sh", "topic": "t0pic"},
        "3 nye lejligheder på Østerbro",   # æøå must not break the header
        "body med æøå beholdes i UTF-8",
        click_url="https://example.dk/1",
    )
    assert ok is True
    req = captured["req"]
    assert req.full_url == "https://ntfy.sh/t0pic"
    title = req.get_header("Title")
    title.encode("latin-1")  # would raise if unsafe
    assert "lejligheder" in title
    assert req.get_header("Click") == "https://example.dk/1"
    assert req.data.decode("utf-8") == "body med æøå beholdes i UTF-8"
