# Contributing

The most valuable contribution is a new source — a Danish rental site
boligvagten can't watch yet. It's a small, well-trodden path: every source is
one module with one interesting function.

## Adding a source

### 1. Find where the data lives

Open the site's search page with DevTools → **Network** and reload. In order
of preference:

1. **A JSON API** (filter by XHR/Fetch). Many sites load listings from a JSON
   endpoint you can call directly — the most robust option.
   Example: [sources/kereby.py](sources/kereby.py).
2. **A framework data endpoint.** Remix, Next.js and friends can serve a
   page's data by URL tweak (`?_data=...` for Remix, `/_next/data/...` for
   Next.js). Example: [sources/cej.py](sources/cej.py).
3. **Server-rendered HTML.** Regex the listing cards out. Anchor your
   patterns on stable-looking attributes (semantic ids/classes, not build
   hashes). Examples: [sources/cityapartment.py](sources/cityapartment.py),
   [sources/boligportal.py](sources/boligportal.py).

### 2. Write the module

```bash
cp sources/_template.py sources/yoursite.py
```

Fill in `KEY`, `LABEL` and `parse()`. The contract:

- `parse(body, conf)` is **pure** — no network, body in, `list[Listing]` out.
  That's what makes it testable offline.
- `fetch(conf)` stays one line (`fetch_all(conf, parse)`) unless the site
  needs multi-request pagination.
- IDs are stable across polls and prefixed: `f"{KEY}:{site_id}"`.
- Unknown values are `None`, never `0` or `""` — the filter layer treats
  `None` as "don't drop what we can't judge".
- Don't filter by price/size/keywords in the parser — that's config's job
  (`filters.py`). Structural skips (parking spots, sold units) do belong in
  the parser.

### 3. Register it

Add the module to `REGISTRY` in [sources/__init__.py](sources/__init__.py)
and give [config.example.py](config.example.py) a commented entry that
explains how someone points the URL at *their* city.

### 4. Prove it with a fixture

Save a trimmed real response (a handful of listings, strip bulk/tracking
junk) to `tests/fixtures/yoursite.<html|json|txt>` and add a test to
[tests/test_parsers.py](tests/test_parsers.py) asserting the parsed fields of
at least one listing, plus a garbage-input case.

```bash
pip install pytest ruff   # or: pip install -e ".[dev]"
pytest -q && ruff check .
```

### 5. PR checklist

- [ ] `parse()` pure, tested against a committed fixture
- [ ] stable prefixed IDs; unknown fields are `None`
- [ ] registered in `sources/__init__.py`
- [ ] documented entry in `config.example.py`
- [ ] `pytest` and `ruff check .` pass
- [ ] no personal data anywhere (searches, topics, contact details)

## Other contributions

Bug fixes, new filter keys, new notification channels — all welcome. Keep the
core dependency-free (stdlib only); anything heavier belongs behind an
optional extra like the Playwright-based auto-contact.

## A note on scraping etiquette

Sources should poll gently (the default 60–180 s jitter), identify listings
by stable IDs, and never automate actions on a site beyond reading public
listings — the CEJ contact-form filler is the deliberate, opt-in exception
and new automation like it needs a clear safety story (dry-run default,
screenshots, explicit opt-in).
