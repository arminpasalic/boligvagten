"""Shared plumbing for listing sources: the Listing model and HTTP/HTML helpers."""
import html as htmllib
import re
import urllib.request
from dataclasses import dataclass

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@dataclass
class Listing:
    """One rental listing, normalized across all sources.

    Unknown values are None — filters let None pass rather than dropping
    a listing we can't fully parse.
    """

    source: str            # registry key of the source, e.g. "cej"
    id: str                # globally unique, prefixed with the source, e.g. "cej:abc123"
    name: str              # short human-readable title
    address: str           # street + area, best effort ("?" if unknown)
    rooms: int | None
    size_m2: int | None
    price_dkk: int | None  # monthly rent
    url: str               # direct link to the listing


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def strip_html(text):
    """Drop tags, unescape entities, collapse whitespace — visible text only."""
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


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
