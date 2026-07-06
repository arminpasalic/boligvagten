"""Source registry.

Adding a site takes two steps:
  1. Copy sources/_template.py to sources/yoursite.py and fill in parse().
  2. Import it and add it to REGISTRY below.
Everything else (polling, filtering, deduping, notifications) is generic.
"""
from . import boligportal, boligsiden, cej, cityapartment, kereby
from .base import Listing  # re-export: `from sources import Listing`  # noqa: F401

# Rental sites first, the for-sale market last.
REGISTRY = [cej, cityapartment, boligportal, kereby, boligsiden]


def enabled(sources_cfg):
    """(module, conf) for every registered source enabled in the config dict."""
    out = []
    for mod in REGISTRY:
        conf = sources_cfg.get(mod.KEY) or {}
        if conf and conf.get("enabled", True):
            out.append((mod, conf))
    return out
