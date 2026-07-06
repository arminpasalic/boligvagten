"""Parser tests against recorded fixtures (trimmed real responses, July 2026).

parse() functions are pure (no network), so these run offline and in CI.
If a site redesigns and its parser breaks, re-record the fixture and adjust.
"""
import json
from pathlib import Path

import pytest

from boligvagten.sources import boligportal, cej, cityapartment, kereby
from boligvagten.sources.base import Listing

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
    assert boligportal.parse("<html><body>no cards here</body></html>") == []


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
