"""City Apartment (cityapartment.dk) — private administrator, Copenhagen.

Plain WordPress search page; listings are server-rendered <article> blocks,
so we parse the HTML directly. Filters (price, size) live in the query
string — set them on the site and copy the URL (see config.example.py).
"""
import re

from .base import Listing, fetch_all, strip_html

KEY = "cityapartment"
LABEL = "City Apartment"

# Each listing is an <article id="post-NNNNN" class="... cityapartments ...">
_ARTICLE = re.compile(
    r'<article id="post-(\d+)"[^>]*cityapartments[^>]*>(.*?)</article>',
    re.DOTALL,
)


def parse(body, conf=None):
    fallback_url = (conf or {}).get("url", "https://cityapartment.dk/")
    out = []
    for m in _ARTICLE.finditer(body):
        post_id, block = m.group(1), m.group(2)
        href_m = re.search(r'href="(https://cityapartment\.dk/[^"]+)"', block)
        text = strip_html(block)
        size = re.search(r"(\d+)\s*m²", text)
        price = re.search(r"(\d[\d.,]*)\s*DKK", text)
        rooms = re.search(r"(\d+)-room", text, re.IGNORECASE)
        zipc = re.search(r"Zip code\s*(\d+)", text)
        # Address is the token between the size and "Zip code".
        addr_m = re.search(r"m²\s+(.+?)\s+Zip code", text)
        out.append(Listing(
            source=KEY,
            id=f"city:{post_id}",
            name=text[:120],
            address=(addr_m.group(1) if addr_m else "")
            + (f", {zipc.group(1)}" if zipc else ""),
            rooms=int(rooms.group(1)) if rooms else None,
            size_m2=int(size.group(1)) if size else None,
            price_dkk=int(price.group(1).replace(".", "").replace(",", ""))
            if price else None,
            url=href_m.group(1) if href_m else fallback_url,
        ))
    return out


def fetch(conf):
    return fetch_all(conf, parse)
