"""Kereby (kereby.dk, formerly kerebyudlejning.dk) — private administrator, Copenhagen.

Listings come from the Jorato tenancy API that Kereby's site itself uses —
clean JSON, no HTML parsing. The API returns everything public; price/area
preferences belong in the `filters` section of the source config.

Listing pages live on kereby.dk under an address slug
(/bolig/strandboulevarden-61-5-th-2100-kobenhavn/), not under the API id,
and the slug can't be derived reliably ("København Ø" becomes "kobenhavn").
So fetch() also reads the site's list of published pages (WordPress REST)
and matches each listing by street + postcode. A listing whose page isn't
published yet links to the listings overview instead.
"""
import json
import re
import unicodedata

from .base import Listing, ParserHealthError, fetch_all, http_get

KEY = "kereby"
LABEL = "Kereby"
DEFAULT_URL = (
    "https://api.jorato.com/tenancies"
    "?visibility=public&showAll=true&key=2gXoBtKvFMMgKJ1VBJ5G5pNr2GD"
)
INDEX_URL = "https://kereby.dk/bolig/"
PAGE_URL = "https://kereby.dk/bolig/{slug}/"
PAGES_API = "https://kereby.dk/wp-json/wp/v2/jorato-cases?per_page=100&page={page}&_fields=slug"


def slugify(text):
    """WordPress-style slug: 'Nørrebrogade 156, st. tv 2200' -> 'norrebrogade-156-st-tv-2200'."""
    text = text.lower().replace("ø", "o").replace("æ", "ae").replace("å", "a")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def page_slugs(get=http_get, max_pages=5):
    """Slugs of every listing page published on kereby.dk."""
    slugs = []
    for page in range(1, max_pages + 1):
        batch = json.loads(get(PAGES_API.format(page=page)))
        slugs.extend(item["slug"] for item in batch if item.get("slug"))
        if len(batch) < 100:
            break
    return slugs


def page_url(address, slugs):
    """The listing's page for an API address dict, or None if not published."""
    key = slugify(f"{address.get('street') or ''} {address.get('zipCode') or ''}")
    if not key or not slugs:
        return None
    matches = sorted({s for s in slugs if s == key or s.startswith(key + "-")})
    return PAGE_URL.format(slug=matches[0]) if len(matches) == 1 else None


def parse(body, conf=None, slugs=None):
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ParserHealthError("Kereby response is missing its expected 'items' list")
    out = []
    for it in data["items"]:
        if not isinstance(it, dict) or not it.get("id"):
            raise ParserHealthError("Kereby returned an item without a stable ID")
        # Structural skips (not user preferences): parking lots, sold units, ...
        if it.get("classification") != "Residential":
            continue
        if it.get("state") != "Available":
            continue
        addr = it.get("address") or {}
        size = (it.get("size") or {}).get("value")
        rent = (it.get("monthlyRent") or {}).get("value")
        out.append(Listing(
            source=KEY,
            id=f"kereby:{it['id']}",
            name=it.get("title", ""),
            address=", ".join(filter(None, [
                addr.get("street"), addr.get("zipCode"), addr.get("city"),
            ])) or "?",
            rooms=it.get("rooms"),
            size_m2=int(size) if size else None,
            price_dkk=int(rent) if rent else None,
            url=page_url(addr, slugs) or INDEX_URL,
        ))
    return out


def _slugs_or_none():
    try:
        return page_slugs()
    except Exception:
        return None  # links fall back to the overview; listings still arrive


def fetch(conf):
    slugs = _slugs_or_none()
    return fetch_all(conf, lambda body, c: parse(body, c, slugs))


def resolve_page_url(tenancy_id, api_url=DEFAULT_URL):
    """Look up one listing's page now (used by auto-contact before visiting it)."""
    data = json.loads(http_get(api_url))
    for it in data.get("items") or []:
        if it.get("id") == tenancy_id:
            return page_url(it.get("address") or {}, page_slugs())
    return None
