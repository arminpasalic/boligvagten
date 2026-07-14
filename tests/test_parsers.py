"""Parser tests against recorded fixtures (trimmed real responses, July 2026).

parse() functions are pure (no network), so these run offline and in CI.
If a site redesigns and its parser breaks, re-record the fixture and adjust.
"""
import json
from pathlib import Path

import pytest

from boligvagten.sources import boligportal, boligsiden, cej, cityapartment, kereby
from boligvagten.sources.base import Listing, ParserHealthError

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------- CEJ

def test_cej_parse_fields():
    items = cej.parse(load("cej.txt"))
    assert len(items) == 2
    first = items[0]
    assert first == Listing(
        source="cej",
        id="cej:f71591e20715809baadd8e73604591e3",
        name="1-værelses lejlighed på Frederiksberg",
        address="Nordre Fasanvej 119, 3. 16, 2000 Frederiksberg",
        rooms=1,
        size_m2=29,
        price_dkk=6929,
        url="https://udlejning.cej.dk/boliger/f71591e20715809baadd8e73604591e3",
    )
    # The second item exists so filter tests can exclude it by keyword.
    assert "Ballerup" in items[1].name


def test_cej_parse_rejects_garbage():
    with pytest.raises(RuntimeError, match="deferred data"):
        cej.parse("<html>not a remix data response</html>")


# ---------------------------------------------------------------- City Apartment

def test_cityapartment_parse_fields():
    items = cityapartment.parse(load("cityapartment.html"))
    assert [it.id for it in items] == ["city:32173", "city:99999"]
    first = items[0]
    assert first.source == "cityapartment"
    assert first.address == "Saxovej 75 A-L, 5210"
    assert (first.rooms, first.size_m2, first.price_dkk) == (1, 32, 5000)
    assert first.url == "https://cityapartment.dk/cityapartments/saxovej-75e-st-3/"
    # Dotted thousands separator is normalized.
    assert items[1].price_dkk == 9000


def test_cityapartment_parse_empty_page():
    assert cityapartment.parse("<html><body>no listings</body></html>") == []


def test_cityapartment_detects_changed_markup():
    with pytest.raises(ParserHealthError, match="neither apartment articles"):
        cityapartment.parse("<html><body>Welcome to our redesigned search</body></html>")
    with pytest.raises(ParserHealthError, match="no direct listing link"):
        cityapartment.parse('<article id="post-123" class="cityapartments">broken</article>')


# ---------------------------------------------------------------- Boligportal

def test_boligportal_parse_fields():
    items = boligportal.parse(load("boligportal.html"))
    assert [it.id for it in items] == ["bp:5472444", "bp:5647910"]
    first = items[0]
    assert first == Listing(
        source="boligportal",
        id="bp:5472444",
        name="lejlighed 50 m²",
        address="Brønshøj , Gadelandet",
        rooms=2,
        size_m2=50,
        price_dkk=12700,
        url="https://www.boligportal.dk/lejligheder/k%C3%B8benhavn/50m2-2-vaer-id-5472444",
    )


def test_boligportal_parse_empty_page():
    assert boligportal.parse("<html><body>no listings</body></html>") == []


def test_boligportal_detects_changed_markup():
    with pytest.raises(ParserHealthError, match="neither listing-card markup"):
        boligportal.parse("<html><body>Welcome to our redesigned search</body></html>")
    with pytest.raises(ParserHealthError, match="no valid listing links"):
        boligportal.parse('<html><a class="AdCardSrp__Link" href="/new-url-shape">x</a></html>')


# ---------------------------------------------------------------- Boligsiden

def test_boligsiden_parse_fields():
    # Fixture holds 4 cases: two complete, one sold (skipped), one missing
    # its optional numbers (rooms/fee/year → None).
    items = boligsiden.parse(load("boligsiden.json"))
    assert len(items) == 3
    first = items[0]
    assert first == Listing(
        source="boligsiden",
        id="bs:ce2c61f4-db62-4ce6-b665-daa4e087940e",
        name="Renoveret 2-værelses på Islands Brygge med skøn sydvestvendt altan",
        address="Gunløgsgade 22, 3. 2, 2300 København S",
        rooms=2,
        size_m2=47,
        price_dkk=3975000,
        url="https://www.boligsiden.dk/adresse/gunloegsgade-22-3-2-2300-koebenhavn-s",
        deal="sale",
        monthly_fee_dkk=3645,
        year_built=1970,
        description=first.description,  # long text — checked separately below
    )
    assert "elevator" in first.description.lower()
    # Ground floor renders Danish-style ("st."), not floor "0".
    assert items[1].address == "Vigerslevvej 336, st. tv, 2500 Valby"
    # Missing optionals stay None — the filter layer treats None as "keep".
    assert (items[2].rooms, items[2].monthly_fee_dkk, items[2].year_built) == (None, None, None)


def test_boligsiden_parse_rejects_garbage():
    with pytest.raises(json.JSONDecodeError):
        boligsiden.parse("<html>not json</html>")
    with pytest.raises(RuntimeError, match="no 'cases'"):
        boligsiden.parse('{"unexpected": true}')


def test_boligsiden_fetch_paginates_newest_first(monkeypatch):
    fixture = json.loads(load("boligsiden.json"))
    pages = {
        1: {"cases": fixture["cases"][:2], "totalHits": 3},
        2: {"cases": fixture["cases"][3:4], "totalHits": 3},
        3: {"cases": [], "totalHits": 3},  # must never be requested
    }
    requested = []

    def fake_get(url, timeout=30):
        page = int(url.split("page=")[-1].split("&")[0])
        requested.append(url)
        return json.dumps(pages[page])

    monkeypatch.setattr(boligsiden, "http_get", fake_get)
    conf = {"url": "https://api.boligsiden.dk/search/cases?municipalities=x", "max_pages": 5}
    items = boligsiden.fetch(conf)
    # totalHits satisfied after page 2 — page 3 is never fetched.
    assert len(requested) == 2
    assert requested[0].endswith("page=1") and requested[1].endswith("page=2")
    assert [it.id[:11] for it in items] == ["bs:ce2c61f4", "bs:6e86ccd5", "bs:4dbdff19"]


def test_boligsiden_fetch_honors_max_pages(monkeypatch):
    fixture = json.loads(load("boligsiden.json"))
    many = {"cases": fixture["cases"][:2], "totalHits": 999}
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        return json.dumps(many)

    monkeypatch.setattr(boligsiden, "http_get", fake_get)
    boligsiden.fetch({"url": "https://api.example/search?x=1"})  # default max_pages=2
    assert len(calls) == 2


# ---------------------------------------------------------------- Kereby

def test_kereby_parse_skips_nonresidential_and_unavailable():
    # Fixture holds 4 items: available flat, parking/commercial unit,
    # reserved flat, and an expensive-but-available flat.
    items = kereby.parse(load("kereby.json"))
    assert [it.id for it in items] == [
        "kereby:a8ead8ef-2720-4143-943f-f712cb755771",
        "kereby:140b3307-a27a-48f2-8a90-70d6205daa1e",
    ]
    first = items[0]
    assert first.address == "Valby Langgade 36, 5. tv, 2500, Valby"
    assert (first.rooms, first.size_m2, first.price_dkk) == (3, 86, 17200)
    # Price filtering is NOT the parser's job — the expensive one stays.
    assert items[1].price_dkk == 25650


def test_kereby_parse_rejects_garbage():
    with pytest.raises(json.JSONDecodeError):
        kereby.parse("this is not json")
    with pytest.raises(ParserHealthError, match="expected 'items' list"):
        kereby.parse('{"unexpected": []}')
    with pytest.raises(ParserHealthError, match="without a stable ID"):
        kereby.parse('{"items": [{"classification": "Residential"}]}')
