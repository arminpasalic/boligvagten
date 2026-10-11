"""Heimstaden (heimstaden.dk) — big private landlord, including youth/student units.

Its "Ledige lejeboliger" page carries every available Heimstaden rental in
Denmark as JSON in an inline script — `var _rentals = [{...}, ...];` — so
one request covers it all (the page's map and filters run on that list).
robots.txt disallows /api/; this reads only the public page.

Which units become listings (structural, set in the source config):
  unit_types   Heimstaden's own unit type (UnikType); default
               ["Studiebolig", "Ungdomsbolig"]. [] = every type.
  properties   building names (EjendomNavn) to keep whatever their unit
               type, e.g. ["Domus Vista"].
A unit is kept when it matches either. Narrow the area with the source's
"filters" (include_keywords on the city, e.g. "København", "Frederiksberg").
"""
from .base import (
    BOLIGVAGTEN_USER_AGENT,
    Listing,
    ParserHealthError,
    amenity_set,
    embedded_json,
    http_get,
    source_urls,
)

KEY = "heimstaden"
LABEL = "Heimstaden"
SEARCH_URL = "https://www.heimstaden.dk/ledige-lejeboliger/"
UNIT_URL = "https://www.heimstaden.dk/lejebolig/{slug}/"
DEFAULT_UNIT_TYPES = ("Studiebolig", "Ungdomsbolig")

# Faciliteter names whose value says "Ja" → base.AMENITY_LABELS.
AMENITIES = {
    "Altan/terrasse": ("balcony",),
    "Elevator": ("elevator",),
    "Parkering": ("parking",),
}


def _yes(value):
    """ "Ja" / "Ja + gæster" count; "Ja, i nogle typer" (only some units) doesn't."""
    text = str(value or "").strip().lower()
    return text.startswith("ja") and "nogle" not in text


def _amenities(rental):
    codes = [f.get("name") for f in rental.get("Faciliteter") or []
             if isinstance(f, dict) and _yes(f.get("value"))]
    found = set(amenity_set(codes, AMENITIES))
    if (rental.get("facilities") or {}).get("petsAllowed"):
        found.add("pets")
    return frozenset(found)


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number > 0 else None


def _wanted(rental, conf):
    conf = conf or {}
    types = conf.get("unit_types", DEFAULT_UNIT_TYPES)
    properties = conf.get("properties") or ()
    if rental.get("EjendomNavn") in properties:
        return True
    return not types or rental.get("UnikType") in types


def parse(body, conf=None):
    rentals = embedded_json(body, "var _rentals =")
    if not isinstance(rentals, list):
        raise ParserHealthError("Heimstaden: no '_rentals' list in the page")
    out = []
    for r in rentals:
        if r.get("Status") == "Reserveret" or not _wanted(r, conf):
            continue
        city = " ".join(str(x) for x in (r.get("PostNr"), r.get("ByNavn")) if x)
        out.append(Listing(
            source=KEY,
            id=f"{KEY}:{r['SagsNr']}",   # the letting case — a re-let unit gets a new one
            name=r.get("EjendomNavn") or r.get("UnikType") or "Heimstaden",
            address=", ".join(x for x in (r.get("Adresse1"), city) if x) or "?",
            rooms=_number(r.get("Rum")),
            size_m2=_number(r.get("Areal")),
            price_dkk=_number(r.get("Leje")),
            url=UNIT_URL.format(slug=r["slug"]) if r.get("slug") else SEARCH_URL,
            amenities=_amenities(r),
        ))
    return out


def fetch(conf):
    """One request for the whole country; parse() keeps what conf asks for."""
    out, seen = [], set()
    for url in source_urls(conf) or [SEARCH_URL]:
        for listing in parse(http_get(url, user_agent=BOLIGVAGTEN_USER_AGENT), conf):
            if listing.id not in seen:
                seen.add(listing.id)
                out.append(listing)
    return out
