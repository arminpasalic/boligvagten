"""Boligportal (boligportal.dk) — Denmark's biggest rental portal.

The search page is server-rendered React with hashed utility classes, so we
anchor on the listing URL scheme (".../<type>/<city>/<size>-<rooms>-vaer-id-N")
rather than on markup: the class names churn with every redesign, the link
shape is public and stable. Each card's visible meta is read from the <h3>
title, the area/street line under it, and the bold price.

City and filters live in the URL path/query — browse to your search on the
site and copy the URL (see config.example.py).

Results come newest first, 18 per page, paged with &offset=N. One page per
poll catches every new listing; "max_pages" (default 1) walks further back
to also see older ones still on the market.
"""
import json
import re

from .base import Listing, ParserHealthError, http_get, known_empty_page, source_urls, strip_html

KEY = "boligportal"
LABEL = "Boligportal"
BASE = "https://www.boligportal.dk"

# Anchor that opens a listing card: href="/lejligheder/koebenhavn/90m2-3-vaer-id-5511000"
CARD_RE = re.compile(r'<a\b[^>]*\shref="(/[^"]*?-id-(\d+))"[^>]*>')

# The page also embeds its data as JSON; each ad there carries a "features"
# dict of booleans. Its keys → base.AMENITY_LABELS.
STORE_RE = re.compile(r'<script id="store" type="application/json">(.*?)</script>', re.DOTALL)
FEATURES = {
    "balcony": "balcony",
    "elevator": "elevator",
    "washing_machine": "washing_machine",
    "dryer": "dryer",
    "dishwasher": "dishwasher",
    "furnished": "furnished",
    "parking": "parking",
    "pet_friendly": "pets",
}


def _amenities_by_id(body):
    """{listing id: amenities} from the embedded store — best effort, {} if absent."""
    m = STORE_RE.search(body)
    if not m:
        return {}
    try:
        store = json.loads(m.group(1))
    except ValueError:
        return {}
    out, stack = {}, [store]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if isinstance(node.get("id"), int) and isinstance(node.get("features"), dict):
                out[str(node["id"])] = frozenset(
                    FEATURES[k] for k, v in node["features"].items() if v is True and k in FEATURES
                )
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


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

    amenities = _amenities_by_id(body)
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
            amenities=amenities.get(listing_id, frozenset()),
        ))

    if not out and not known_empty_page(body):
        raise ParserHealthError(
            "Boligportal card marker was present, but no valid listing links were parsed"
        )
    return out


def _with_offset(url, n):
    """The search URL from result n on. Page 1 stays the URL as given."""
    if not n:
        return url
    if re.search(r"[?&]offset=\d+", url):
        return re.sub(r"([?&])offset=\d+", rf"\g<1>offset={n}", url)
    return f"{url}{'&' if '?' in url else '?'}offset={n}"


def fetch(conf):
    """Newest-first: page 1, then older pages up to max_pages per URL."""
    max_pages = conf.get("max_pages", 1)
    out, seen = [], set()
    for url in source_urls(conf):
        offset = 0
        for _ in range(max_pages):
            page = parse(http_get(_with_offset(url, offset)), conf)
            new = [it for it in page if it.id not in seen]
            if not new:  # empty page, or the site repeated the last one
                break
            seen.update(it.id for it in new)
            out.extend(new)
            offset += len(page)
    return out
