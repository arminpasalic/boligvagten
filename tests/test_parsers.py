"""Parser tests against recorded fixtures (trimmed real responses, July 2026).

parse() functions are pure (no network), so these run offline and in CI.
If a site redesigns and its parser breaks, re-record the fixture and adjust.
"""
import json
from pathlib import Path

import pytest

from boligvagten.sources import (
    blaekhus,
    boligportal,
    boligsiden,
    canvas,
    cej,
    cityapartment,
    heimstaden,
    kereby,
    sdk,
)
from boligvagten.sources.base import Listing, ParserHealthError, embedded_json

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


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


def test_cej_parse_amenities():
    body = "data:" + json.dumps({"searchResponse": {"items": [{
        "id": "abc",
        "amenities": ["elevator", "balconyOrTerrace", "sharedLaundry", "courtyard"],
        "appliances": ["washerDryer", "dishwasher", "oven"],
    }]}})
    (item,) = cej.parse(body)
    # Shared laundry is not an in-unit washing machine; unknown codes drop out.
    assert item.amenities == {"elevator", "balcony", "washing_machine", "dryer", "dishwasher"}


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
    assert [it.id for it in items] == ["bp:5511000", "bp:5671274"]
    first = items[0]
    assert first == Listing(
        source="boligportal",
        id="bp:5511000",
        name="3 vær. lejlighed på 90 m²",
        address="Herlev, Hørkær",
        rooms=3,
        size_m2=90,
        price_dkk=15350,
        url="https://www.boligportal.dk/lejligheder/k%C3%B8benhavn/90m2-3-vaer-id-5511000",
    )
    # Prices carrying øre ("12.962,68 kr.") truncate to whole kroner.
    assert items[1].price_dkk == 12962


def test_boligportal_parse_amenities_from_embedded_store():
    store = {"props": {"page_props": {"results": [
        {"id": 5511000, "url": "/x-id-5511000", "features": {
            "balcony": True, "elevator": False, "washing_machine": True,
            "furnished": None, "pet_friendly": True, "senior_friendly": True,
        }},
    ]}}}
    body = (load("boligportal.html")
            + f'<script id="store" type="application/json">{json.dumps(store)}</script>')
    items = boligportal.parse(body)
    # Only explicit True counts; unmapped keys (senior_friendly) are ignored.
    assert items[0].amenities == {"balcony", "washing_machine", "pets"}
    # A card without a store entry simply has no amenities.
    assert items[1].amenities == frozenset()


def test_boligportal_parse_tolerates_broken_store():
    body = load("boligportal.html") + '<script id="store" type="application/json">{oops</script>'
    assert [it.amenities for it in boligportal.parse(body)] == [frozenset(), frozenset()]


def _card(listing_id):
    return (f'<a class="x" href="/lejligheder/k%C3%B8benhavn/30m2-1-vaer-id-{listing_id}">'
            f'<h3>1 vær. lejlighed på 30 m²</h3></a>')


def test_boligportal_fetch_pages_back_by_offset(monkeypatch):
    pages = {0: [1, 2], 2: [3, 4], 4: [5]}
    requested = []

    def fake_get(url, timeout=30):
        requested.append(url)
        offset = int(url.split("offset=")[1]) if "offset=" in url else 0
        return "".join(_card(i) for i in pages[offset])

    monkeypatch.setattr(boligportal, "http_get", fake_get)
    url = "https://www.boligportal.dk/lejligheder/k%C3%B8benhavn/?max_monthly_rent=9000"
    items = boligportal.fetch({"url": url, "max_pages": 2})
    assert [it.id for it in items] == ["bp:1", "bp:2", "bp:3", "bp:4"]
    assert requested == [url, url + "&offset=2"]  # page 1 is the URL as given


def test_boligportal_fetch_stops_when_a_page_brings_nothing_new(monkeypatch):
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        return _card(1)  # the site keeps serving the same page

    monkeypatch.setattr(boligportal, "http_get", fake_get)
    items = boligportal.fetch({"url": "https://www.boligportal.dk/x/", "max_pages": 8})
    assert [it.id for it in items] == ["bp:1"]
    assert calls == ["https://www.boligportal.dk/x/", "https://www.boligportal.dk/x/?offset=1"]


def test_boligportal_fetch_default_is_one_page(monkeypatch):
    calls = []
    monkeypatch.setattr(boligportal, "http_get", lambda url, timeout=30: calls.append(url) or _card(1))
    boligportal.fetch({"url": "https://www.boligportal.dk/x/"})
    assert len(calls) == 1


def test_boligportal_parse_empty_page():
    assert boligportal.parse("<html><body>no listings</body></html>") == []


def test_boligportal_detects_changed_markup():
    with pytest.raises(ParserHealthError, match="neither listing-card markup"):
        boligportal.parse("<html><body>Welcome to our redesigned search</body></html>")
    # A listing link whose id segment is gone is a schema change, not an empty page.
    with pytest.raises(ParserHealthError, match="neither listing-card markup"):
        boligportal.parse('<html><a href="/lejligheder/koebenhavn/new-url-shape">x</a></html>')


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


def test_kereby_links_point_to_the_published_kereby_dk_page():
    pages = [
        "valby-langgade-36-5-tv-2500-valby",
        "sortedam-dossering-45-5-tv-2200-kobenhavn-n",
        "sortedam-dossering-45-5-tv-2200-kobenhavn-n",  # WP lists some pages twice
        "sortedam-dossering-4-1-th-2200-kobenhavn-n",   # shares a prefix, not a match
    ]
    api = json.dumps([
        {"slug": s, "link": f"https://kereby.dk/jorato-case/{s}/"} for s in pages
    ])
    slugs = kereby.page_slugs(get=lambda url: api)
    urls = {it.id: it.url for it in kereby.parse(load("kereby.json"), slugs=slugs)}
    assert urls["kereby:a8ead8ef-2720-4143-943f-f712cb755771"] == (
        "https://kereby.dk/jorato-case/valby-langgade-36-5-tv-2500-valby/"
    )
    assert urls["kereby:140b3307-a27a-48f2-8a90-70d6205daa1e"] == (
        "https://kereby.dk/jorato-case/sortedam-dossering-45-5-tv-2200-kobenhavn-n/"
    )


def test_kereby_link_falls_back_to_the_slug_when_wp_omits_it():
    slugs = kereby.page_slugs(get=lambda url: json.dumps([{"slug": "a-1-2500"}]))
    assert slugs == {"a-1-2500": "https://kereby.dk/jorato-case/a-1-2500/"}


def test_kereby_unpublished_page_links_to_the_overview_not_a_404():
    items = kereby.parse(load("kereby.json"), slugs=[])
    assert {it.url for it in items} == {kereby.INDEX_URL}
    assert kereby.slugify("Godthåbsvej 62B, parterre 2000") == "godthabsvej-62b-parterre-2000"
    assert kereby.slugify("Fælledvej 23, 5. th 2200") == "falledvej-23-5-th-2200"


def test_kereby_parse_amenities():
    body = json.dumps({"items": [{
        "id": "k1", "classification": "Residential", "state": "Available",
        "tenancyFacilities": ["Balcony", "BasementRoom"],
        "propertyFacilities": ["Elevator", "CommunalLaundry"],
        "appliances": ["WasherDryer", "Dishwasher"],
        "additionalDetails": {"furnished": True, "petsAllowed": False},
        "petsAllowed": False,
    }]})
    (item,) = kereby.parse(body)
    assert item.amenities == {
        "balcony", "elevator", "washing_machine", "dryer", "dishwasher", "furnished",
    }


def test_kereby_parse_rejects_garbage():
    with pytest.raises(json.JSONDecodeError):
        kereby.parse("this is not json")
    with pytest.raises(ParserHealthError, match="expected 'items' list"):
        kereby.parse('{"unexpected": []}')
    with pytest.raises(ParserHealthError, match="without a stable ID"):
        kereby.parse('{"items": [{"classification": "Residential"}]}')


# ---------------------------------------------------------------- s.dk

def test_sdk_parse_fields():
    items = sdk.parse(load("sdk.json"))
    assert [it.id for it in items] == ["sdk:4", "sdk:5", "sdk:262", "sdk:453253"]
    assert items[1] == Listing(
        source="sdk",
        id="sdk:5",
        name="Ågården",
        address="Kapelvej 52-56, 2200",
        rooms=1,             # smallest of the building's room types [1, 2]
        size_m2=None,
        price_dkk=2474,      # lowest rent of "2474 - 5464 DKK/month"
        url="https://mit.s.dk/studiebolig/building/5/",
    )


def test_sdk_empty_page_parses_to_nothing():
    # A page past the end, as s.dk really returns it.
    assert sdk.parse(load("sdk_empty.json")) == []


def test_sdk_parse_rejects_garbage():
    with pytest.raises(json.JSONDecodeError):
        sdk.parse("<html>maintenance</html>")
    with pytest.raises(ParserHealthError, match="no 'results'"):
        sdk.parse('{"detail": "Not found."}')


def test_sdk_fetch_walks_every_page_politely(monkeypatch):
    page1 = load("sdk.json")
    last = json.dumps({"count": 5, "results": [{"pk": 999, "name": "Ny", "rooms": [1]}]})
    pages = {"1": page1.replace('"count": 244', '"count": 5'), "2": last}
    calls = []

    def fake_get(url, timeout=30, user_agent=None):
        calls.append((url, user_agent))
        return pages[url.rsplit("page=", 1)[1]]

    monkeypatch.setattr(sdk, "http_get", fake_get)
    items = sdk.fetch({"url": sdk.SEARCH_URL})
    assert [it.id for it in items][-1] == "sdk:999"   # new buildings land on the last page
    assert [u for u, _ in calls] == [
        "https://mit.s.dk/api/v2/public/buildings/search/?page_size=100&page=1",
        "https://mit.s.dk/api/v2/public/buildings/search/?page_size=100&page=2",
    ]   # stopped at count — no request for an empty page 3
    assert all(ua.startswith("boligvagten/") for _, ua in calls)


def test_sdk_fetch_stops_on_empty_page_and_respects_max_pages(monkeypatch):
    bodies = []

    def serve(fixture):
        return lambda url, **kw: bodies.append(url) or load(fixture)

    monkeypatch.setattr(sdk, "http_get", serve("sdk_empty.json"))
    assert sdk.fetch({}) == []           # default URL; empty page ends the walk
    assert len(bodies) == 1

    bodies.clear()
    monkeypatch.setattr(sdk, "http_get", serve("sdk.json"))
    sdk.fetch({"max_pages": 2})          # count says 244, but max_pages caps it
    assert len(bodies) == 2


def test_sdk_private_kitchen_bath_reads_the_buildings_table():
    table = load("sdk_building.json")    # "Eget køkken ja … Eget bad ja"
    assert sdk.private_kitchen_bath(table) is True
    no_kitchen = table.replace("ja<br></td>", "nej<br></td>", 1)   # first row: Eget køkken
    assert "nej<br>" in no_kitchen
    assert sdk.private_kitchen_bath(no_kitchen) is False
    # Newer buildings describe their rooms in prose — unknown, not "no".
    assert sdk.private_kitchen_bath(load("sdk_building_prose.json")) is None


def test_sdk_deep_check_fetches_only_when_asked_and_fails_open():
    listing = sdk.parse(load("sdk.json"))[0]
    calls = []

    def get(url, body):
        calls.append(url)
        return body

    table = load("sdk_building.json")
    no_bath = table.replace("Eget bad</td>", "Eget bad</td><td>nej</td>").replace(
        "&nbsp;ja&nbsp;<div", "<div")
    assert sdk.private_kitchen_bath(no_bath) is False

    assert sdk.deep_check(listing, {}, get=lambda u: get(u, no_bath)) is True
    assert calls == []                    # option off → no building-page fetch
    on = {"private_kitchen_bath": True}
    assert sdk.deep_check(listing, on, get=lambda u: get(u, table)) is True
    assert sdk.deep_check(listing, on, get=lambda u: get(u, no_bath)) is False
    assert calls == ["https://mit.s.dk/api/v2/public/buildings/4/"] * 2
    prose = load("sdk_building_prose.json")
    assert sdk.deep_check(listing, on, get=lambda u: prose) is True

    def boom(url):
        raise OSError("offline")

    assert sdk.deep_check(listing, on, get=boom) is True


# ---------------------------------------------------------------- shared helpers

def test_embedded_json_reads_the_value_after_a_marker():
    page = '<script>var a = 1; var _rentals = [{"x": "];"}];\nvar b = [];</script>'
    assert embedded_json(page, "var _rentals =") == [{"x": "];"}]   # not fooled by "];"
    assert embedded_json(page, "var missing =") is None


def test_http_get_asks_for_gzip_and_unpacks_it(monkeypatch):
    import gzip
    import io

    from boligvagten.sources import base

    sent = {}

    class Resp(io.BytesIO):
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(req, timeout):
        sent.update(req.headers)
        return Resp(gzip.compress("Ærø".encode()))

    monkeypatch.setattr(base.urllib.request, "urlopen", urlopen)
    assert base.http_get("https://x.dk", user_agent="ua/1") == "Ærø"
    assert sent == {"User-agent": "ua/1", "Accept-encoding": "gzip"}


# ---------------------------------------------------------------- Blækhus

def test_blaekhus_parse_fields():
    items = blaekhus.parse(load("blaekhus.html"))
    assert [it.id for it in items] == ["blaekhus:651999", "blaekhus:649958", "blaekhus:649961"]
    assert items[0] == Listing(
        source="blaekhus",
        id="blaekhus:651999",
        name="Blækhus Frederiksberg",
        address="Finsensvej 15, st. 2, Frederiksberg",
        rooms=1,
        size_m2=26,
        price_dkk=8700,
        url="https://blaekhus-living.dk/property/finsensvej-15-st-2/",
    )


def test_blaekhus_skips_reserved_and_sold_units():
    page = load("blaekhus.html")
    reserved = page.replace('{"name":"available","value":"Ledig"}',
                            '{"name":"reserved","value":"Reserveret"}', 1)
    assert [it.id for it in blaekhus.parse(reserved)] == ["blaekhus:649958", "blaekhus:649961"]
    empty = page[:page.index("properties:")] + "properties: [],\n}));</script>"
    assert blaekhus.parse(empty) == []      # a building with nothing free


def test_blaekhus_parse_rejects_a_changed_page():
    with pytest.raises(ParserHealthError, match="no 'properties'"):
        blaekhus.parse("<html><body>Vi opdaterer siden</body></html>")


def test_blaekhus_fetch_reads_each_building_once_identified(monkeypatch):
    calls = []

    def fake_get(url, timeout=30, user_agent=None):
        calls.append((url, user_agent))
        return load("blaekhus.html")

    monkeypatch.setattr(blaekhus, "http_get", fake_get)
    items = blaekhus.fetch({"urls": ["https://b.dk/frb/", "https://b.dk/valby/"]})
    assert len(items) == 3                  # same units twice → deduped
    assert [u for u, _ in calls] == ["https://b.dk/frb/", "https://b.dk/valby/"]
    assert all(ua.startswith("boligvagten/") for _, ua in calls)


# ---------------------------------------------------------------- Heimstaden

def test_heimstaden_keeps_youth_and_student_units_by_default():
    items = heimstaden.parse(load("heimstaden.html"), {})
    assert [it.name for it in items] == ["C.F. Richs Vej", "Flintholm II",
                                         items[2].name]      # + Hørparken, Kolding
    assert items[0] == Listing(
        source="heimstaden",
        id="heimstaden:46893",
        name="C.F. Richs Vej",
        address="C.F. Richs Vej 105D, 1. 103, 2000 Frederiksberg",
        rooms=1,
        size_m2=26,
        price_dkk=8700,
        url="https://www.heimstaden.dk/lejebolig/cf-richs-vej-105d-1-103-2000-frederiksberg/",
        # "Altan/terrasse: Ja, i nogle typer" is only some units → not claimed
        amenities=frozenset({"elevator", "parking"}),
    )
    assert "Kolding" in items[2].address


def test_heimstaden_unit_types_and_properties_options():
    page = load("heimstaden.html")
    assert len(heimstaden.parse(page, {"unit_types": []})) == 6         # every type
    named = heimstaden.parse(page, {"unit_types": ["Ungdomsbolig"],
                                    "properties": ["C.F. Richs Vej"]})
    # the building's NPI flat comes along because the building is named
    assert [it.id for it in named] == ["heimstaden:46893", "heimstaden:42206"]
    reserved = page.replace('"Status":"Klar til udlejning"', '"Status":"Reserveret"', 1)
    assert [it.id for it in heimstaden.parse(reserved, {"unit_types": ["Ungdomsbolig"]})] == []


def test_heimstaden_parse_rejects_a_changed_page():
    with pytest.raises(ParserHealthError, match="no '_rentals'"):
        heimstaden.parse("<html><script>var rentals = [];</script></html>", {})


# ---------------------------------------------------------------- Canvas

def test_canvas_parse_fields():
    items = canvas.parse(load("canvas.html"))
    # Standard Studio lists 3 units, the sold-out type none, Superior Studio 1
    # (that one sits in the page's second data chunk).
    assert [it.id for it in items] == ["canvas:443470", "canvas:443507",
                                       "canvas:443509", "canvas:443556"]
    assert items[0] == Listing(
        source="canvas",
        id="canvas:443470",
        name="Canvas Standard Studio (from 15.10.2026)",
        address="Helsinkigade 27, 2150 Nordhavn",
        rooms=1,
        size_m2=26,          # "26-31" → smallest
        price_dkk=8550,      # "000=8550"
        url=("https://nordhavn-rentcafewebsiteuk.securerc.co.uk/onlineleasing/nordhavn/"
             "oleapplication.aspx?stepname=RentalOptions&myOlePropertyId=186146"
             "&FloorPlanID=1112675&UnitID=443470&header=1"),
        amenities=frozenset({"furnished"}),
    )
    assert (items[3].name, items[3].price_dkk) == ("Canvas Superior Studio (from 01.11.2026)",
                                                   10400)


def test_canvas_parse_rejects_a_changed_page():
    with pytest.raises(ParserHealthError, match="no floor plans"):
        canvas.parse('<script>self.__next_f.push([1,"0:[]\\n"])</script>')
