# Changelog

All notable changes to boligvagten are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-10-02

### Added
- Auto-contact for Kereby (the listing page's "Interesseret?" form), next to
  CEJ. Each site is Off / Test only / Send, set in the browser page (with a
  "Try it now" button that shows the filled form) or in the new `CONTACT`
  block in `config.py`. Old `CEJ_CONTACT` configs keep working.
- The headless browser auto-contact needs is downloaded temporarily when it
  is missing and deleted on exit, both in the browser page and the CLI.
- `--contact-test URL`: fill in the form on one CEJ or Kereby listing
  without sending it. `scripts/check_contact.py` runs both sites' forms on
  live listings with the reply faked, to catch site redesigns.
- Local browser interface (`boligvagten --web`, or `python -m boligvagten
  --web`): set searches, filters and phone alerts, see status and a live log,
  and run a one-shot search, all in English or Danish. It listens on
  127.0.0.1 only, with a per-run token. Closing the tab stops it; settings
  persist in `~/.config/boligvagten/settings.json`, seeded from an existing
  `config.py`. Changing searches or filters re-baselines quietly instead of
  alerting on every listing the new search returns.
- Double-click download for people without git or a terminal: each release
  attaches `boligvagten-<version>.zip` with "Start Boligvagten" launchers for
  macOS and Windows. They use the installed Python (3.9+) or a temporary
  uv-managed Python that is deleted on exit.

### Fixed
- CEJ auto-contact reported "SENT" whenever any visible text contained
  "tak" — including the form's own heading "Kontakt" — so failed submissions
  looked successful. The outcome is now read from CEJ's reply to the
  submission and its "Din besked er sendt" confirmation.
- CEJ's cookie banner can appear seconds after page load and then blocked
  every click of the form; it is now dismissed whenever it shows up.
- A failed auto-contact (e.g. the browser not installed yet) was never
  retried. Failures before anything was submitted now retry up to three
  times; anything after pressing Send is held for manual review instead.
- Kereby alerts linked to kerebyudlejning.dk/bolig/<id>, which now redirects
  to a "page not found" on kereby.dk. Links point to the listing's kereby.dk
  page (or the listings overview until that page is published).
- Boligportal parser now follows the September 2026 redesign, which replaced
  the `AdCardSrp__Link` card class with hashed utility classes. Cards are
  matched on the listing URL scheme (`…-id-<digits>`) instead of on CSS class
  names, and fields are read from the card's title, area line, and price.
  Prices carrying øre (`12.962,68 kr.`) no longer mis-parse.

### Changed
- `--contact-cej URL` is now an alias of `--contact-test` and never sends,
  regardless of `live_send` (it used to send when `live_send` was on).
- Auto-contact actions older than 12 hours are skipped, and pending ones are
  cancelled when their site is switched off.
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

[Unreleased]: https://github.com/arminpasalic/boligvagten/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/arminpasalic/boligvagten/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/arminpasalic/boligvagten/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/arminpasalic/boligvagten/releases/tag/v0.1.0
