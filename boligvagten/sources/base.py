"""Shared plumbing for listing sources: the Listing model and HTTP/HTML helpers."""
from __future__ import annotations  # keeps `int | None` working on Python 3.9

import gzip
import html as htmllib
import json
import re
import urllib.request
from dataclasses import dataclass

from .. import __version__

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
# For sites happy to see who's asking: polite and identifiable, not a browser.
BOLIGVAGTEN_USER_AGENT = f"boligvagten/{__version__} (personal housing watcher)"


class ParserHealthError(RuntimeError):
    """The response was readable but no longer matched a source's expected schema."""


def known_empty_page(body):
    """True for explicit zero-result messages, not merely missing listing markup."""
    text = strip_html(body).lower()
    markers = (
        "ingen boliger",
        "ingen lejeboliger",
        "ingen ledige boliger",
        "ingen resultater",
        "no apartments",
        "no listings",
        "no results",
    )
    return any(marker in text for marker in markers)


# Shared amenity vocabulary. Sources map their own codes onto these keys
# (Listing.amenities); config HIGHLIGHTS picks from them, and the value is how
# the tag reads in a notification.
AMENITY_LABELS = {
    "balcony": "altan",
    "elevator": "elevator",
    "washing_machine": "vaskemaskine",
    "dryer": "tørretumbler",
    "dishwasher": "opvaskemaskine",
    "furnished": "møbleret",
    "parking": "parkering",
    "pets": "husdyr tilladt",
}


def amenity_set(codes, mapping):
    """Map a source's amenity codes onto AMENITY_LABELS keys; unknown codes are dropped.

    `mapping` values are tuples, so one code can imply several amenities
    (a washer-dryer is both a washing machine and a dryer).
    """
    out = set()
    for code in codes or ():
        out.update(mapping.get(code, ()))
    return frozenset(out)


@dataclass
class Listing:
    """One listing, normalized across all sources — rentals and for-sale alike.

    Unknown values are None — filters let None pass rather than dropping
    a listing we can't fully parse.
    """

    source: str            # registry key of the source, e.g. "cej"
    id: str                # globally unique, prefixed with the source, e.g. "cej:abc123"
    name: str              # short human-readable title
    address: str           # street + area, best effort ("?" if unknown)
    rooms: int | None
    size_m2: int | None
    price_dkk: int | None  # monthly rent — or cash price when deal == "sale"
    url: str               # direct link to the listing

    # Defaulted fields — rental sources can ignore everything below.
    deal: str = "rent"                  # "rent" | "sale"
    monthly_fee_dkk: int | None = None  # ejerudgift (sale listings)
    year_built: int | None = None
    description: str | None = None      # long free text when the source has it inline
    amenities: frozenset = frozenset()  # AMENITY_LABELS keys, from structured site data


def http_get(url, timeout=30, user_agent=USER_AGENT):
    # gzip keeps big listing pages (up to ~1.6 MB) light on every poll.
    req = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                               "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode("utf-8")


def embedded_json(body, marker):
    """The JSON value written right after `marker` in a page's inline script; None if absent.

    For server-rendered pages that hand their data to JavaScript, e.g.
    `var _rentals = [...];` — read with marker "var _rentals =".
    """
    i = body.find(marker)
    if i < 0:
        return None
    start = i + len(marker)
    while start < len(body) and body[start].isspace():
        start += 1
    return json.JSONDecoder().raw_decode(body, start)[0]


def strip_html(text):
    """Drop tags, unescape entities, collapse whitespace — visible text only."""
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def fetch_description(listing):
    """Visible text of the listing's own page — for description_keywords filtering."""
    return strip_html(http_get(listing.url))


def source_urls(conf):
    """A source config may give a single `url` or a list of `urls` (e.g. several cities)."""
    if conf.get("urls"):
        return list(conf["urls"])
    if conf.get("url"):
        return [conf["url"]]
    return []


def fetch_all(conf, parse):
    """Default fetch: GET every configured URL, parse, dedupe by listing id."""
    out, seen = [], set()
    for url in source_urls(conf):
        for listing in parse(http_get(url), conf):
            if listing.id not in seen:
                seen.add(listing.id)
                out.append(listing)
    return out
