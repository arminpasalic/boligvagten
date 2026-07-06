"""Config-driven listing filters, applied after parsing — same rules for every source.

Two layers, both optional:
  * the global FILTERS dict in config.py (applies to everything)
  * a per-source "filters" dict inside a SOURCES entry (applies on top)

Supported keys:
  max_price_dkk / min_price_dkk       price bounds (monthly rent, or cash
                                      price for for-sale sources)
  min_rooms / max_rooms               room count bounds
  min_size_m2 / max_size_m2           size bounds
  min_monthly_fee_dkk /               ejerudgift bounds — for-sale listings
  max_monthly_fee_dkk                 only (rentals have no monthly fee)
  exclude_keywords                    drop when any appears in name/address/
                                      description (case-insensitive)
  include_keywords                    keep only when at least one appears in
                                      name/address/description — e.g. ["altan"]
  description_keywords                like include_keywords but matched against
                                      the full listing description; handled
                                      separately (see deep_apply) because it
                                      may cost one HTTP fetch per listing

A listing with an unknown (None) value always passes the numeric bounds:
better one alert too many than a silently missed apartment.
"""


def _bounds_ok(value, f, min_key, max_key):
    """None value passes; otherwise both configured bounds must hold."""
    if value is None:
        return True
    if f.get(max_key) is not None and value > f[max_key]:
        return False
    if f.get(min_key) is not None and value < f[min_key]:
        return False
    return True


def _haystack(listing):
    return f"{listing.name} {listing.address} {listing.description or ''}".lower()


def passes(listing, *filter_dicts):
    """True if the listing survives every filter dict given."""
    for f in filter_dicts:
        if not f:
            continue
        if not _bounds_ok(listing.price_dkk, f, "min_price_dkk", "max_price_dkk"):
            return False
        if not _bounds_ok(listing.rooms, f, "min_rooms", "max_rooms"):
            return False
        if not _bounds_ok(listing.size_m2, f, "min_size_m2", "max_size_m2"):
            return False
        if not _bounds_ok(listing.monthly_fee_dkk, f,
                          "min_monthly_fee_dkk", "max_monthly_fee_dkk"):
            return False
        if f.get("exclude_keywords"):
            hay = _haystack(listing)
            if any(kw.lower() in hay for kw in f["exclude_keywords"]):
                return False
        if f.get("include_keywords"):
            hay = _haystack(listing)
            if not any(kw.lower() in hay for kw in f["include_keywords"]):
                return False
    return True


def apply(listings, *filter_dicts):
    return [it for it in listings if passes(it, *filter_dicts)]


def none_active(global_filters, sources_cfg):
    """True when neither the global FILTERS nor any source sets a filter value.

    Not an error — source URLs usually encode the search — but worth one
    startup note so nobody watches an unfiltered firehose by accident.
    """
    dicts = [global_filters or {}]
    for conf in (sources_cfg or {}).values():
        if isinstance(conf, dict):
            dicts.append(conf.get("filters") or {})
    return not any(v not in (None, [], "") for f in dicts for v in f.values())
