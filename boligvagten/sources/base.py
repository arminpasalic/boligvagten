"""Shared plumbing for listing sources: the Listing model and HTTP/HTML helpers."""
from __future__ import annotations  # keeps `int | None` working on Python 3.9

import html as htmllib
import re
import urllib.request
from dataclasses import dataclass

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


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


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


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
