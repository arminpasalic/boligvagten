"""Config-driven listing filters, applied after parsing — same rules for every source.

Two layers, both optional:
  * the global FILTERS dict in config.py (applies to everything)
  * a per-source "filters" dict inside a SOURCES entry (applies on top)

Supported keys:
  max_price_dkk / min_price_dkk   monthly rent bounds
  min_rooms                       at least this many rooms
  min_size_m2                     at least this many m²
  exclude_keywords                drop when any appears in name/address
                                  (case-insensitive) — e.g. ["studiebolig"]

A listing with an unknown (None) value always passes the numeric bounds:
better one alert too many than a silently missed apartment.
"""


def passes(listing, *filter_dicts):
    """True if the listing survives every filter dict given."""
    for f in filter_dicts:
        if not f:
            continue
        price, rooms, size = listing.price_dkk, listing.rooms, listing.size_m2
        if f.get("max_price_dkk") is not None and price is not None \
                and price > f["max_price_dkk"]:
            return False
        if f.get("min_price_dkk") is not None and price is not None \
                and price < f["min_price_dkk"]:
            return False
        if f.get("min_rooms") is not None and rooms is not None \
                and rooms < f["min_rooms"]:
            return False
        if f.get("min_size_m2") is not None and size is not None \
                and size < f["min_size_m2"]:
            return False
        if f.get("exclude_keywords"):
            hay = f"{listing.name} {listing.address}".lower()
            if any(kw.lower() in hay for kw in f["exclude_keywords"]):
                return False
    return True


def apply(listings, *filter_dicts):
    return [it for it in listings if passes(it, *filter_dicts)]
