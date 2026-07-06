"""Filter behavior: bounds, keyword excludes, None-passthrough, layering."""
from test_parsers import load

from boligvagten.filters import apply, passes
from boligvagten.sources import cej
from boligvagten.sources.base import Listing


def mk(**kw):
    base = dict(source="x", id="x:1", name="Lejlighed", address="Gade 1, København",
                rooms=2, size_m2=60, price_dkk=10000, url="https://x.dk/1")
    base.update(kw)
    return Listing(**base)


def test_no_filters_passes_everything():
    assert passes(mk())
    assert passes(mk(), None, {})


def test_price_bounds():
    assert not passes(mk(price_dkk=15000), {"max_price_dkk": 12000})
    assert passes(mk(price_dkk=12000), {"max_price_dkk": 12000})
    assert not passes(mk(price_dkk=900), {"min_price_dkk": 2000})


def test_rooms_and_size_minimums():
    assert not passes(mk(rooms=1), {"min_rooms": 2})
    assert passes(mk(rooms=2), {"min_rooms": 2})
    assert not passes(mk(size_m2=40), {"min_size_m2": 50})


def test_none_values_pass_numeric_bounds():
    # Unknown data must never silently hide a listing.
    it = mk(price_dkk=None, rooms=None, size_m2=None)
    assert passes(it, {"max_price_dkk": 1, "min_price_dkk": 99999,
                       "min_rooms": 99, "min_size_m2": 999})


def test_exclude_keywords_case_insensitive_on_name_and_address():
    assert not passes(mk(name="Lækker STUDIEBOLIG"), {"exclude_keywords": ["studiebolig"]})
    assert not passes(mk(address="Hovedgaden 3, Ballerup"), {"exclude_keywords": ["ballerup"]})
    assert passes(mk(), {"exclude_keywords": ["ballerup"]})


def test_global_and_per_source_filters_stack():
    global_f = {"max_price_dkk": 20000}
    source_f = {"exclude_keywords": ["ballerup"]}
    items = [
        mk(id="x:ok"),
        mk(id="x:pricey", price_dkk=25000),
        mk(id="x:excluded", address="Ballerup Torv 1"),
    ]
    kept = apply(items, global_f, source_f)
    assert [it.id for it in kept] == ["x:ok"]


def test_reproduces_old_hardcoded_cej_student_filter():
    # The pre-refactor fetcher dropped student/Ballerup/Næstved listings in code;
    # the same behavior is now plain config (see config.example.py).
    items = cej.parse(load("cej.txt"))
    kept = apply(items, {"exclude_keywords": [
        "studiebolig", "studerende", "studie", "student",
        "rungsted", "ballerup", "næstved",
    ]})
    assert [it.id for it in kept] == ["cej:f71591e20715809baadd8e73604591e3"]
