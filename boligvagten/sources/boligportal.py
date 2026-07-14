"""Boligportal (boligportal.dk) — Denmark's biggest rental portal.

The search page is server-rendered React; rather than fight the markup we
split on the ad-card link class and regex the visible text out of each chunk.
City and filters live in the URL path/query — browse to your search on the
site and copy the URL (see config.example.py).
"""
import re

from .base import Listing, ParserHealthError, fetch_all, known_empty_page, strip_html

KEY = "boligportal"
LABEL = "Boligportal"
BASE = "https://www.boligportal.dk"


def parse(body, conf=None):
    # Each card starts with an <a class="AdCardSrp__Link ..." href="..."> and the
    # visible meta (rooms, size, area, address, price) lives in sibling nodes
    # until the next card begins. Split on the link class to get per-card chunks.
    parts = body.split("AdCardSrp__Link")
    if len(parts) == 1:
        if known_empty_page(body):
            return []
        raise ParserHealthError(
            "Boligportal response has neither listing-card markup nor an explicit empty result"
        )
    out = []
    seen_ids = set()
    for chunk in parts[1:]:
        # Cap length to avoid pulling unrelated page content from the tail.
        chunk = chunk[:20000]
        href_m = re.search(r'href="(/[^"]+-id-(\d+))"', chunk)
        if not href_m:
            continue
        path, listing_id = href_m.group(1), href_m.group(2)
        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        # Strip styles, svgs, tags to get visible text.
        text = re.sub(r"<style[^>]*>.*?</style>", " ", chunk, flags=re.DOTALL)
        text = re.sub(r"<svg[^>]*>.*?</svg>", " ", text, flags=re.DOTALL)
        text = strip_html(text)

        size = re.search(r"(\d+)\s*m²", text)
        rooms = re.search(r"(\d+)\s*vær", text)
        price = re.search(r"([\d.]+)\s*kr\.", text)
        # Address line sits between "m² " and " <price> kr." — e.g.
        # "3 vær. lejlighed på 98 m² København Ø , Vordingborggade 16.333 kr."
        addr_m = re.search(r"m²\s+(.+?)\s+[\d.]+\s*kr\.", text)
        kind = "værelse" if "/v%C3%A6relser/" in path else "lejlighed"

        out.append(Listing(
            source=KEY,
            id=f"bp:{listing_id}",
            name=f"{kind} {size.group(0) if size else ''}".strip(),
            address=addr_m.group(1).strip() if addr_m else "?",
            rooms=int(rooms.group(1)) if rooms else None,
            size_m2=int(size.group(1)) if size else None,
            price_dkk=int(price.group(1).replace(".", "")) if price else None,
            url=BASE + path,
        ))
    if not out and not known_empty_page(body):
        raise ParserHealthError(
            "Boligportal card marker was present, but no valid listing links were parsed"
        )
    return out


def fetch(conf):
    return fetch_all(conf, parse)
