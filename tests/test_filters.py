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


def test_rooms_and_size_maximums():
    assert not passes(mk(rooms=5), {"max_rooms": 3})
    assert passes(mk(rooms=3), {"max_rooms": 3})
    assert not passes(mk(size_m2=200), {"max_size_m2": 120})


def test_monthly_fee_bounds_for_sale_listings():
    sale = mk(deal="sale", price_dkk=3_975_000, monthly_fee_dkk=3645)
    assert passes(sale, {"max_monthly_fee_dkk": 4000})
    assert not passes(sale, {"max_monthly_fee_dkk": 3000})
    assert not passes(sale, {"min_monthly_fee_dkk": 5000})
    # Rentals have no monthly fee (None) — the bound must not drop them.
    assert passes(mk(), {"max_monthly_fee_dkk": 3000})


def test_none_values_pass_numeric_bounds():
    # Unknown data must never silently hide a listing.
    it = mk(price_dkk=None, rooms=None, size_m2=None)
    assert passes(it, {"max_price_dkk": 1, "min_price_dkk": 99999,
                       "min_rooms": 99, "max_rooms": 1,
                       "min_size_m2": 999, "max_size_m2": 1,
                       "max_monthly_fee_dkk": 1})


def test_exclude_keywords_case_insensitive_on_name_and_address():
    assert not passes(mk(name="Lækker STUDIEBOLIG"), {"exclude_keywords": ["studiebolig"]})
    assert not passes(mk(address="Hovedgaden 3, Ballerup"), {"exclude_keywords": ["ballerup"]})
    assert passes(mk(), {"exclude_keywords": ["ballerup"]})


def test_keywords_also_match_inline_description():
    it = mk(description="Dejlig lejlighed med ALTAN og badekar.")
    assert not passes(it, {"exclude_keywords": ["badekar"]})
    assert passes(it, {"include_keywords": ["altan"]})


def test_include_keywords_keep_only_matches():
    assert passes(mk(name="2V med altan"), {"include_keywords": ["altan", "terrasse"]})
    assert not passes(mk(), {"include_keywords": ["altan", "terrasse"]})
    # No description (None) must not crash the haystack build.
    assert not passes(mk(description=None), {"include_keywords": ["altan"]})


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


def test_none_active_detects_unfiltered_setups():
    from boligvagten.filters import none_active
    assert none_active(None, {})
    assert none_active({"max_price_dkk": None, "exclude_keywords": []}, {})
    assert not none_active({"max_price_dkk": 14000}, {})
    assert not none_active(None, {"cej": {"url": "u", "filters": {"min_rooms": 2}}})


def test_reproduces_old_hardcoded_cej_student_filter():
    # The pre-refactor fetcher dropped student/Ballerup/Næstved listings in code;
    # the same behavior is now plain config (see config.example.py).
    items = cej.parse(load("cej.txt"))
    kept = apply(items, {"exclude_keywords": [
        "studiebolig", "studerende", "studie", "student",
        "rungsted", "ballerup", "næstved",
    ]})
    assert [it.id for it in kept] == ["cej:f71591e20715809baadd8e73604591e3"]
