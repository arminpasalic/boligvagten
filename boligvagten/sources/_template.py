"""Skeleton for a new listings source — copy me to boligvagten/sources/yoursite.py.

How to find the data (in rough order of preference):

1. JSON API. Open the site's search page with browser DevTools → Network →
   XHR/Fetch and reload. Many housing sites (Kereby, Boligsiden, ...) fetch
   listings from a JSON endpoint you can call directly — that's the most
   robust option. See kereby.py, or boligsiden.py for a paginated one.

2. Framework data endpoints. Remix/Next/Nuxt sites often expose the page's
   loader data by tweaking the URL (`?_data=...` for Remix, `/_next/data/...`
   for Next.js). See cej.py.

3. Server-rendered HTML. As a last resort, regex the listing cards out of
   the page. Keep the regexes narrow and anchored on stable attributes
   (ids, class names that look hand-written, not build hashes).
   See cityapartment.py and boligportal.py.

For-sale site? Set deal="sale" on each Listing (price_dkk becomes the cash
price, monthly_fee_dkk the ejerudgift) — see boligsiden.py.

Checklist before opening a PR (see CONTRIBUTING.md):
  [ ] parse() is pure (no network) so it can be tested against a fixture
  [ ] ids are prefixed and stable across polls, e.g. "yoursite:12345"
  [ ] unknown fields are None, not 0 or ""
  [ ] a trimmed fixture + test in tests/ proves parse() works
  [ ] the module is added to REGISTRY in boligvagten/sources/__init__.py
  [ ] config.example.py gained a section with a "how to get your URL" note
"""
from .base import Listing, fetch_all  # noqa: F401 — Listing is used once you fill in parse()

KEY = "yoursite"            # config key in SOURCES; also used as the id prefix
LABEL = "Your Site"         # human name used in log lines
LISTING_URL = "https://www.yoursite.dk/listing/{id}"


def parse(body, conf=None):
    """Turn one raw response body into a list of Listings. No network here."""
    out = []
    # for it in json.loads(body)["results"]:
    #     out.append(Listing(
    #         source=KEY,
    #         id=f"{KEY}:{it['id']}",
    #         name=it["headline"],
    #         address=it.get("address") or "?",
    #         rooms=it.get("rooms"),                # None when unknown
    #         size_m2=it.get("sizeM2"),             # None when unknown
    #         price_dkk=it.get("monthlyRent"),      # None when unknown
    #         url=LISTING_URL.format(id=it["id"]),
    #     ))
    return out


def fetch(conf):
    """GET every configured URL and parse. fetch_all handles url/urls + dedupe."""
    return fetch_all(conf, parse)
