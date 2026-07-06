"""Boligsiden (boligsiden.dk) — the for-sale market, all of Denmark.

Boligsiden's frontend queries api.boligsiden.dk/search/cases, a public JSON
API, so we do too. Useful query params (build the URL by hand — the website's
address bar does not expose these):

  municipalities=københavn      area filter; repeat the param for several.
  zipCodes=2100                 alternative area filter (also repeatable).
                                (`cities=` looks tempting but returns nothing.)
  addressTypes=condo,cooperative,villa,terraced house,villa apartment,farm
  priceMin / priceMax           cash price bounds, DKK
  numberOfRoomsMin / -Max, areaMin / -Max
  monthlyExpenseMin / -Max      ejerudgift bounds, DKK/month
  sortBy=daysListed&sortAscending=true    newest first — keep this so new
                                listings surface on page 1; the monitor only
                                walks `max_pages` pages (default 2) per poll.
  per_page=50                   page size

Listings carry their full description inline (`descriptionBody`), so the
description_keywords filter costs no extra requests for this source.
"""
import json
import re

from .base import Listing, http_get

KEY = "boligsiden"
LABEL = "Boligsiden (til salg)"

# addressType → the label a Danish reader expects in a notification.
_TYPES = {
    "condo": "Ejerlejlighed",
    "cooperative": "Andelsbolig",
    "villa": "Villa",
    "terraced house": "Rækkehus",
    "villa apartment": "Villalejlighed",
    "farm": "Landejendom",
    "hobby farm": "Nedlagt landbrug",
    "holiday house": "Sommerhus",
}


def _int(value):
    return int(value) if value is not None else None


def _address(addr):
    """"Gunløgsgade 22, 3. 2, 2300 København S" — floor "0" is stuen ("st.")."""
    road = addr.get("roadName") or "?"
    if addr.get("houseNumber"):
        road += f" {addr['houseNumber']}"
    parts = [road]
    floor, door = addr.get("floor"), addr.get("door")
    floor_txt = None
    if floor is not None:
        floor_txt = "st." if str(floor) == "0" else f"{floor}."
    if door:
        floor_txt = f"{floor_txt} {door}" if floor_txt else str(door)
    if floor_txt:
        parts.append(floor_txt)
    tail = " ".join(str(x) for x in (addr.get("zipCode"), addr.get("cityName")) if x)
    if tail:
        parts.append(tail)
    return ", ".join(parts)


def parse(body, conf=None):
    data = json.loads(body)
    cases = data.get("cases")
    if cases is None:
        raise RuntimeError("Boligsiden: no 'cases' in response")
    out = []
    for c in cases:
        # Structural skip: sold/withdrawn cases still appear in some queries.
        if c.get("status") not in (None, "open"):
            continue
        kind = _TYPES.get(c.get("addressType"), c.get("addressType") or "Bolig")
        address = _address(c.get("address") or {})
        slug = c.get("slugAddress")
        out.append(Listing(
            source=KEY,
            id=f"bs:{c['caseID']}",
            name=c.get("descriptionTitle") or f"{kind} til salg",
            address=address,
            rooms=_int(c.get("numberOfRooms")),
            size_m2=_int(c.get("housingArea")),
            price_dkk=_int(c.get("priceCash")),
            url=(f"https://www.boligsiden.dk/adresse/{slug}" if slug
                 else f"https://www.boligsiden.dk/viderestilling/{c['caseID']}"),
            deal="sale",
            monthly_fee_dkk=_int(c.get("monthlyExpense")),
            year_built=_int(c.get("yearBuilt")),
            description=c.get("descriptionBody"),
        ))
    return out


def _with_page(url, n):
    if re.search(r"[?&]page=\d+", url):
        return re.sub(r"([?&])page=\d+", rf"\g<1>page={n}", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}page={n}"


def fetch(conf):
    """Paginated fetch: newest-first page 1, then up to max_pages in total."""
    max_pages = conf.get("max_pages", 2)
    out, seen = [], set()
    urls = conf.get("urls") or ([conf["url"]] if conf.get("url") else [])
    for url in urls:
        fetched = 0
        for page in range(1, max_pages + 1):
            body = http_get(_with_page(url, page))
            for listing in parse(body, conf):
                if listing.id not in seen:
                    seen.add(listing.id)
                    out.append(listing)
            meta = json.loads(body)
            fetched += len(meta.get("cases") or [])
            if not meta.get("cases") or fetched >= meta.get("totalHits", 0):
                break
    return out
