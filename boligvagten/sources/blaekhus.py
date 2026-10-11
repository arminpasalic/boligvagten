"""Blækhus (blaekhus-living.dk) — private youth/student studios run by EDC Poul Erik Bech.

Rented first come, first served (no seniority list), so speed matters.
Every building has a "Boligliste" page that ships its units to the browser
as JSON in an inline script — `properties: [{...}, ...]` — with rent,
size, rooms and a status (available / reserved / sold). One request per
building; only `available` units become listings.

Copenhagen buildings (one URL each, see config.example.py):
  /frederiksberg/boligliste-frederiksberg/   Finsensvej 15
  /vanloese/boligliste-vanloese/
  /valby/boligliste-valby/
  /valby-m/boligliste-valby-m/
(/aarhus/boligliste-aarhus/ works the same way.)
"""
from .base import (
    BOLIGVAGTEN_USER_AGENT,
    Listing,
    ParserHealthError,
    embedded_json,
    http_get,
    source_urls,
)

KEY = "blaekhus"
LABEL = "Blækhus"


def _positive(value):
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def parse(body, conf=None):
    units = embedded_json(body, "properties:")
    if not isinstance(units, list):
        raise ParserHealthError("Blækhus: no 'properties' list in the Boligliste page")
    out = []
    for u in units:
        if (u.get("status") or {}).get("name") != "available":
            continue  # reserved/sold stay on the list for a while — not for us
        building = u.get("category") or ""   # "Frederiksberg", "Valby M", ...
        address = ", ".join(x for x in (u.get("address"), building) if x)
        out.append(Listing(
            source=KEY,
            id=f"{KEY}:{u['ID']}",
            name=f"Blækhus {building}".strip(),
            address=address or "?",
            rooms=_positive(u.get("rooms")),
            size_m2=_positive(u.get("size_raw")),
            price_dkk=_positive(u.get("monthly_rent_raw")),
            url=u.get("url") or "https://blaekhus-living.dk/",
        ))
    return out


def fetch(conf):
    """One request per building page, one at a time."""
    out, seen = [], set()
    for url in source_urls(conf):
        for listing in parse(http_get(url, user_agent=BOLIGVAGTEN_USER_AGENT), conf):
            if listing.id not in seen:
                seen.add(listing.id)
                out.append(listing)
    return out
