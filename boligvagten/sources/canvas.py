"""Canvas Student (canvas-world.com, run by Greystar) — furnished studios, Copenhagen.

Rented first come, first served through an online booking flow. The
location page is a Next.js app whose server-rendered HTML carries the
page data in `self.__next_f.push([1, "..."])` script chunks. In there,
every floor plan (studio type) is an object starting with
`{"FloorPlanSitecoreID"`: itemId, itemName, price ("000=8550"),
floorPlanArea ("26-31"), unitsAvailable, earliestUnitAvailableDate, and
as children its bookable units, each a RentCafe link carrying its UnitID.

One Listing per bookable unit; price/size/date come from its floor plan.
A plan lists at most 10 units, so while a type has more than 10 free, the
11th only appears once one of the first 10 is booked.
robots.txt disallows /_next/*; this reads only the public location page.
"""
import json
import re

from .base import (
    BOLIGVAGTEN_USER_AGENT,
    Listing,
    ParserHealthError,
    amenity_set,
    http_get,
    source_urls,
)

KEY = "canvas"
LABEL = "Canvas Student"
NORDHAVN_URL = "https://www.canvas-world.com/en/locations/denmark/copenhagen/nordhavn"

_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_UNIT_RE = re.compile(r"[?&]UnitID=(\d+)")
# Floor-plan feature titles → base.AMENITY_LABELS ("Furnished with Kitchenette").
AMENITIES = {"furnished": ("furnished",)}


def _value(obj, key):
    v = obj.get(key)
    return v.get("value") if isinstance(v, dict) else None


def _payload(body):
    """The page's Next.js flight data: every push([1, "…"]) chunk, decoded and joined."""
    return "".join(json.loads(chunk) for chunk in _CHUNK_RE.findall(body))


def _objects(payload):
    """Every JSON object in the payload that starts with "FloorPlanSitecoreID"."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r'\{"FloorPlanSitecoreID"', payload):
        try:
            yield decoder.raw_decode(payload, m.start())[0]
        except ValueError:
            continue


def _price(raw):
    """ "000=8550" → 8550; 0 or junk → None."""
    digits = re.findall(r"\d+", str(raw or ""))
    price = int(digits[-1]) if digits else 0
    return price or None


def _size(raw):
    """ "26-31" → 26 (the smallest of the type)."""
    m = re.match(r"\s*(\d+)", str(raw or ""))
    return int(m.group(1)) if m else None


def _date(raw):
    """ "10/15/2026" (US order) → "15.10.2026"; anything else as given."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(raw or "").strip())
    return f"{int(m.group(2)):02d}.{int(m.group(1)):02d}.{m.group(3)}" if m else raw


def _street(payload):
    m = re.search(r'"address":\{"value":"([^"]+)"\},"city":\{"value":"([^"]*)"\}', payload)
    zip_m = re.search(r'"postalCode":\{"value":"(\d{4})"\}', payload)
    if not m:
        return None
    tail = " ".join(x for x in ((zip_m.group(1) if zip_m else ""), m.group(2)) if x)
    return ", ".join(x for x in (m.group(1), tail) if x)


def parse(body, conf=None):
    payload = _payload(body)
    plans = {}   # plan id → (plan, its units); the page may repeat a plan
    for obj in _objects(payload):
        if "unitsAvailable" not in obj:
            continue
        units = [u for u in (obj.get("children") or {}).get("results") or []
                 if isinstance(u, dict) and u.get("__typename") == "Unit"]
        plan_id = _value(obj, "itemId") or obj.get("name")
        if plan_id not in plans or (units and not plans[plan_id][1]):
            plans[plan_id] = (obj, units)
    if not plans:
        raise ParserHealthError("Canvas: no floor plans in the page data")

    address = _street(payload) or "Canvas Student"
    out, seen = [], set()
    for plan, units in plans.values():
        features = [((f.get("fields") or {}).get("featureTitle") or {}).get("value") or ""
                    for f in (plan.get("features") or {}).get("jsonValue") or []]
        amenities = amenity_set(
            [code for code in AMENITIES if any(code in t.lower() for t in features)], AMENITIES)
        name = _value(plan, "itemName") or "Studio"
        date = _date(_value(plan, "earliestUnitAvailableDate"))
        for unit in units:
            link = _value(unit, "availabilityURL") or ""
            m = _UNIT_RE.search(link)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            out.append(Listing(
                source=KEY,
                id=f"{KEY}:{m.group(1)}",
                name=f"Canvas {name}" + (f" (from {date})" if date else ""),
                address=address,
                rooms=1,
                size_m2=_size(_value(plan, "floorPlanArea")),
                price_dkk=_price(_value(plan, "price")),
                url=link,
                amenities=amenities,
            ))
    return out


def fetch(conf):
    out, seen = [], set()
    for url in source_urls(conf) or [NORDHAVN_URL]:
        for listing in parse(http_get(url, user_agent=BOLIGVAGTEN_USER_AGENT), conf):
            if listing.id not in seen:
                seen.add(listing.id)
                out.append(listing)
    return out
