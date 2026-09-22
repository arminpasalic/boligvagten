# Changelog

All notable changes to boligvagten are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Boligportal parser now follows the September 2026 redesign, which replaced
  the `AdCardSrp__Link` card class with hashed utility classes. Cards are
  matched on the listing URL scheme (`…-id-<digits>`) instead of on CSS class
  names, and fields are read from the card's title, area line, and price.
  Prices carrying øre (`12.962,68 kr.`) no longer mis-parse.

### Changed
- Default polling jitter is now 30–60 seconds.
- Seen IDs and CEJ action status share a versioned, atomically replaced state
  file with legacy migration and last-known-good recovery.
- Failed ntfy deliveries remain pending for the next poll instead of being
  marked seen; CEJ actions use a durable outbox and interrupted submissions
  require manual review rather than being blindly retried.
- HTML/JSON sources now distinguish explicit empty results from unexpected
  response shapes and report parser-health failures.
- CI runs on every pushed branch and builds the distribution. Releases now
  validate SemVer/tag alignment and main ancestry, then lint, test, build, and
  smoke-test the installed wheel before publishing.

## [1.0.0] - 2026-07-06

Boligvagten grows from a rental monitor into a Danish housing watcher:
both markets, installable with one command, still zero dependencies.

### Added
- **Boligsiden source** — the for-sale market (ejerlejligheder, andelsboliger,
  houses, all of Denmark) via Boligsiden's public search API. Polls newest-first
  and reads at most `max_pages` pages per cycle; listing descriptions arrive
  inline. Area filtering via `municipalities=`/`zipCodes=` query params.
- **Install with `uvx boligvagten` / `pipx install boligvagten`** — the project
  is now a real package with a `boligvagten` command; `python3 monitor.py`
  from a clone works exactly as before. Installed runs keep their config in
  `~/.config/boligvagten/`.
- **New filter keys**: `max_rooms`, `max_size_m2`, `min`/`max_monthly_fee_dkk`
  (ejerudgift bounds for sale listings), `include_keywords` (keep only
  matches), and `description_keywords` — matched against the full listing
  description, fetched lazily for new listings only and fail-open.
- Sale-aware notifications: cash price + ejerudgift + byggeår in the message,
  market-split push titles ("2 nye lejeboliger, 1 til salg") with matching tags.
- Startup note when no filters are configured anywhere.

### Changed
- Code moved into the `boligvagten/` package (`sources/` →
  `boligvagten/sources/`); the repo-root `monitor.py` is now a thin launcher.
- Config/state resolution: `$BOLIGVAGTEN_CONFIG` → `./config.py` →
  `~/.config/boligvagten/config.py`, with `seen_listings.json` always next to
  the active config. Existing checkouts are unaffected.
- `exclude_keywords` now also matches inline descriptions, not just
  name + address.

## [0.1.0] - 2026-07-03

Initial public version: clone-and-run monitor for four Danish rental sites
(Boligportal, CEJ, Kereby, City Apartment) with randomized polling,
seen-state diffing, offline backoff, ntfy push + macOS banner onboarding,
config-driven filters, offline parser tests against recorded fixtures, and
the opt-in CEJ contact-form auto-filler (dry-run by default).

[Unreleased]: https://github.com/arminpasalic/boligvagten/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/arminpasalic/boligvagten/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/arminpasalic/boligvagten/releases/tag/v0.1.0
