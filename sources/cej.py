"""CEJ Udlejning (udlejning.cej.dk) — large private administrator, Zealand.

The search page is a Remix app; requesting the search URL with the
`_data=routes%2Fsearch%2Flayout` query param returns the route's loader data
(a deferred-data text stream containing one big JSON object) instead of HTML.

To point this at your own filters: set them on https://udlejning.cej.dk
(price, area, ...), copy the resulting URL and append the `_data` param —
see config.example.py.
"""
import json
import re

from .base import Listing, fetch_all

KEY = "cej"
LABEL = "CEJ Udlejning"
LISTING_URL = "https://udlejning.cej.dk/boliger/{id}"


def parse(body, conf=None):
    match = re.search(r"data:(\{.*\})", body, re.DOTALL)
    if not match:
        raise RuntimeError("CEJ: no deferred data block in response")
    data = json.loads(match.group(1))
    out = []
    for it in data["searchResponse"].get("items", []):
        out.append(Listing(
            source=KEY,
            id=f"cej:{it['id']}",
            name=it.get("name", ""),
            address=(it.get("location") or {}).get("formatted") or "?",
            rooms=it.get("numberOfRooms"),
            size_m2=it.get("floorSize"),
            price_dkk=(it.get("price") or {}).get("amount"),
            url=LISTING_URL.format(id=it["id"]),
        ))
    return out


def fetch(conf):
    return fetch_all(conf, parse)
