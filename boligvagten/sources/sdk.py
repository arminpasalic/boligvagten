"""s.dk (mit.s.dk/studiebolig) — Copenhagen and Zealand student housing (CIU, RIU-Roskilde, Agora).

One Listing per *building*, not per room: s.dk hands out rooms by waiting
list, so the useful alert is "a new building appeared — sign up today".

The new s.dk app reads a public JSON API, so we do too:

  /api/v2/public/buildings/search/?page_size=100&page=N
      {"count": 244, "results": [{"pk", "name", "desc_address", "zipcode",
      "rooms": [1, 2], "min_rent", "max_rent", "committee_abbreviation", ...}]}
  /api/v2/public/buildings/{pk}/
      one building; its "description" is the HTML the building page shows,
      which often (older buildings) holds an "Eget køkken / Eget bad: ja/nej" table.

Buildings come sorted oldest first, so new ones land on the last page and
fetch() walks every page (3 requests for ~250 buildings at page_size=100).
s.dk changes slowly — config.example.py sets min_interval_hours: 24.
"""
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import BOLIGVAGTEN_USER_AGENT, Listing, ParserHealthError, http_get, strip_html

KEY = "sdk"
LABEL = "s.dk (studiebolig)"
SEARCH_URL = "https://mit.s.dk/api/v2/public/buildings/search/?page_size=100"
DETAIL_URL = "https://mit.s.dk/api/v2/public/buildings/{id}/"
BUILDING_URL = "https://mit.s.dk/studiebolig/building/{id}/"
USER_AGENT = BOLIGVAGTEN_USER_AGENT


def _int(value):
    return int(value) if value is not None else None


def parse(body, conf=None):
    data = json.loads(body)
    results = data.get("results") if isinstance(data, dict) else None
    if results is None:
        raise ParserHealthError("s.dk: no 'results' in building search response")
    out = []
    for b in results:
        address = ", ".join(str(x) for x in (b.get("desc_address"), b.get("zipcode")) if x)
        rooms = [r for r in b.get("rooms") or [] if isinstance(r, int)]
        out.append(Listing(
            source=KEY,
            id=f"{KEY}:{b['pk']}",
            name=b.get("name") or "Studiebolig",
            address=address or "?",
            rooms=min(rooms) if rooms else None,
            size_m2=None,
            price_dkk=_int(b.get("min_rent")),
            url=BUILDING_URL.format(id=b["pk"]),
        ))
    return out


def _page_url(url, page):
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "page"] + [("page", str(page))]
    return urlunsplit(parts._replace(query=urlencode(query)))


def _get(url):
    return http_get(url, user_agent=USER_AGENT)


def fetch(conf):
    """Every page, one request at a time, up to max_pages per URL."""
    max_pages = conf.get("max_pages", 5)
    urls = conf.get("urls") or [conf.get("url") or SEARCH_URL]
    out, seen = [], set()
    for url in urls:
        fetched = 0
        for page in range(1, max_pages + 1):
            body = _get(_page_url(url, page))
            items = parse(body, conf)
            for listing in items:
                if listing.id not in seen:
                    seen.add(listing.id)
                    out.append(listing)
            fetched += len(items)
            if not items or fetched >= (json.loads(body).get("count") or 0):
                break
    return out


# ---------- private kitchen + bath (optional, new buildings only) ----------

_ROW_RE = r"eget\s+{}\s*:?\s*(ja|nej)\b"


def private_kitchen_bath(detail_body):
    """True/False from the building's "Eget køkken" + "Eget bad" rows; None if it has none.

    Pure: takes the /buildings/{pk}/ JSON. Newer buildings often describe
    their rooms in prose instead of the table — that's None (unknown).
    """
    text = strip_html(json.loads(detail_body).get("description") or "").lower()
    kitchen = re.search(_ROW_RE.format("køkken"), text)
    bath = re.search(_ROW_RE.format("bad"), text)
    if not kitchen or not bath:
        return None
    return kitchen.group(1) == "ja" and bath.group(1) == "ja"


def deep_check(listing, conf, get=None):
    """Monitor hook, called once per *new* building: False drops the alert.

    Unknown (no table, fetch failed) keeps the building — same fail-open
    rule as every other filter: better one alert too many.
    """
    if not conf.get("private_kitchen_bath"):
        return True
    try:
        body = (get or _get)(DETAIL_URL.format(id=listing.id.split(":", 1)[1]))
        return private_kitchen_bath(body) is not False
    except Exception:
        return True
