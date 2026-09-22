"""Boligportal (boligportal.dk) — Denmark's biggest rental portal.

The search page is server-rendered React with hashed utility classes, so we
anchor on the listing URL scheme (".../<type>/<city>/<size>-<rooms>-vaer-id-N")
rather than on markup: the class names churn with every redesign, the link
shape is public and stable. Each card's visible meta is read from the <h3>
title, the area/street line under it, and the bold price.

City and filters live in the URL path/query — browse to your search on the
site and copy the URL (see config.example.py).
"""
import re

from .base import Listing, ParserHealthError, fetch_all, known_empty_page, strip_html

KEY = "boligportal"
LABEL = "Boligportal"
BASE = "https://www.boligportal.dk"

# Anchor that opens a listing card: href="/lejligheder/koebenhavn/90m2-3-vaer-id-5511000"
CARD_RE = re.compile(r'<a\b[^>]*\shref="(/[^"]*?-id-(\d+))"[^>]*>')


def _price_to_int(raw):
    """'12.962,68' / '15.350' -> 12962 / 15350 (dotted thousands, decimal comma)."""
    return int(raw.split(",")[0].replace(".", "").strip())


def parse(body, conf=None):
    matches = list(CARD_RE.finditer(body))
    if not matches:
        if known_empty_page(body):
            return []
        raise ParserHealthError(
            "Boligportal response has neither listing-card markup nor an explicit empty result"
        )

    out = []
    seen_ids = set()
    for i, m in enumerate(matches):
        path, listing_id = m.group(1), m.group(2)
        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        # The card body runs from this anchor to the start of the next one.
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[m.end():end]

        title_m = re.search(r"<h3[^>]*>(.*?)</h3>", chunk, re.DOTALL)
        title = strip_html(title_m.group(1)) if title_m else ""

        # "Herlev<!-- -->, <!-- -->Hørkær" -> "Herlev, Hørkær"
        addr_m = re.search(r'<p class="[^"]*text-muted[^"]*"[^>]*>(.*?)</p>', chunk, re.DOTALL)
        address = re.sub(r"\s+,", ",", strip_html(addr_m.group(1))) if addr_m else "?"

        price_m = re.search(r'<span class="[^"]*font-bold[^"]*"[^>]*>\s*([\d.,]+)\s*kr\.', chunk)
        size_m = re.search(r"(\d+)\s*m²", title)
        rooms_m = re.search(r"(\d+)\s*vær", title)

        out.append(Listing(
            source=KEY,
            id=f"bp:{listing_id}",
            name=title or "?",
            address=address or "?",
            rooms=int(rooms_m.group(1)) if rooms_m else None,
            size_m2=int(size_m.group(1)) if size_m else None,
            price_dkk=_price_to_int(price_m.group(1)) if price_m else None,
            url=BASE + path,
        ))

    if not out and not known_empty_page(body):
        raise ParserHealthError(
            "Boligportal card marker was present, but no valid listing links were parsed"
        )
    return out


def fetch(conf):
    return fetch_all(conf, parse)
