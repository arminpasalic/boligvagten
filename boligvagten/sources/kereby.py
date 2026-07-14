"""Kereby Udlejning (kerebyudlejning.dk) — private administrator, Copenhagen.

Kereby's Nuxt frontend calls the Jorato tenancy API directly, so we do too —
clean JSON, no HTML parsing. The API returns everything public; price/area
preferences belong in the `filters` section of the source config.
"""
import json

from .base import Listing, ParserHealthError, fetch_all

KEY = "kereby"
LABEL = "Kereby"
LISTING_URL = "https://kerebyudlejning.dk/bolig/{id}"


def parse(body, conf=None):
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
            url=LISTING_URL.format(id=it["id"]),
        ))
    return out


def fetch(conf):
    return fetch_all(conf, parse)
