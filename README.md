# boligvagten 🏠

**Get to Danish rental listings first.** Boligvagten stands watch over multiple
Danish rental sites around the clock and pushes an alert to your phone the
minute something new appears — because in Copenhagen, the difference between
getting a viewing and getting nothing is usually measured in minutes.

[![CI](https://github.com/arminpasalic/boligvagten/actions/workflows/ci.yml/badge.svg)](https://github.com/arminpasalic/boligvagten/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)

```
[2026-07-03T19:09:16] 3 new apartment listing(s):
  • [cej] Nordre Fasanvej 119, 2000 Frederiksberg — 1r, 29m², 6929 DKK/mo
    https://udlejning.cej.dk/boliger/f71591e2...
  • [kereby] Valby Langgade 36, 2500 Valby — 3r, 86m², 17200 DKK/mo
    https://kerebyudlejning.dk/bolig/a8ead8ef...
```
*…and the same message lands on your phone as a push notification.*

## Why this exists

- **The portals aren't enough.** Everyone watches boligportal.dk. The private
  administrators (CEJ, Kereby, City Apartment, …) list great apartments on
  their own sites where far fewer people are looking — boligvagten watches
  both worlds at once.
- **Speed wins.** Popular listings collect hundreds of inquiries within hours.
  An instant push notification (and optionally an auto-filled contact form,
  see below) puts you at the front of the queue.
- **Zero setup friction.** Pure Python standard library — no accounts, no API
  keys, no database, no dependencies. Clone it, run it, subscribe to your
  alert channel, done.
- **Built to be forked.** Sources are plug-in modules, filters and cities are
  config, and the parsers are covered by offline tests. Making it watch *your*
  city or *your* favourite site is a small, documented change.

## Quick start

```bash
git clone https://github.com/arminpasalic/boligvagten.git
cd boligvagten
python3 monitor.py
```

The first run creates your personal `config.py`, generates a private
notification channel, and prints exactly what to do:

```
================================================================
  Get alerts on your phone (takes ~2 minutes)
================================================================
  Your private alert channel:

      https://ntfy.sh/boligvagten-fznm8pj759

  1. Install the free ntfy app:
       iPhone:  https://apps.apple.com/app/ntfy/id1625396347
       Android: https://play.google.com/store/apps/details?id=io.heckel.ntfy
  2. In the app: tap + and subscribe to the topic:

      boligvagten-fznm8pj759

  3. A test notification was just sent — it appears once you subscribe.
================================================================
```

Install the [ntfy](https://ntfy.sh) app, subscribe to your topic, and leave
the monitor running. That's the whole setup.

> Phone notifications ride on the free public [ntfy.sh](https://ntfy.sh)
> service (no account needed). Self-hosting ntfy? Point `NTFY["server"]` at
> your instance in `config.py`.

## Everyday commands

| Command | What it does |
|---|---|
| `python3 monitor.py` | Watch continuously, alert on new listings |
| `python3 monitor.py --list` | One-shot search: print everything matching your filters right now |
| `python3 monitor.py --once` | Run a single check and exit (handy for cron) |
| `python3 monitor.py --test-notify` | Send a test push to every channel |
| `python3 monitor.py --setup` | Re-print the phone setup instructions |
| `python3 monitor.py --contact-cej URL` | Dry-run the CEJ contact form on one listing |

## Configuration

Everything lives in `config.py` — a heavily commented Python file created from
[config.example.py](config.example.py) on first run. It is gitignored: your
topic, your searches, and (if you enable auto-contact) your personal details
never leave your machine.

**Filters** apply to every source, with optional per-source overrides:

```python
FILTERS = {
    "max_price_dkk": 14000,
    "min_rooms": 2,
    "min_size_m2": 50,
    "exclude_keywords": ["studiebolig", "delevenlig"],
}
```

**Another city?** The search URL *is* the search — city, price, size are all
encoded in it. Open the site, set your filters, copy the URL into the source's
config entry. Each entry in `config.example.py` documents the site-specific
trick (Boligportal: just use your city's page, e.g. `/lejeboliger/aarhus/`;
CEJ: append one query param; …).

**Several searches at once?** Give a source a list:

```python
"boligportal": {
    "enabled": True,
    "urls": [
        "https://www.boligportal.dk/lejeboliger/k%C3%B8benhavn/",
        "https://www.boligportal.dk/lejeboliger/aarhus/",
    ],
},
```

**Polling pace**: intervals are randomized (default 60–180 s). Be polite —
faster than ~30 s helps nobody and risks getting the affected site's
attention.

## Supported sources

| Source | Site | Coverage | How it's read |
|---|---|---|---|
| `boligportal` | boligportal.dk | all of Denmark | server-rendered HTML |
| `cej` | udlejning.cej.dk | Zealand / Copenhagen | Remix data endpoint |
| `kereby` | kerebyudlejning.dk | Copenhagen | public JSON API |
| `cityapartment` | cityapartment.dk | Copenhagen | server-rendered HTML |

Want another site? That's the fun part — see
[CONTRIBUTING.md](CONTRIBUTING.md): copy
[sources/_template.py](sources/_template.py), write one `parse()` function,
register it, done. PRs welcome.

## Auto-contact (CEJ) — optional

CEJ listings receive a flood of inquiries almost immediately. Boligvagten can
fill out CEJ's 3-step contact form automatically the moment a listing
appears: your details, your message to the landlord, your profile.

It is **off by default**, and its `live_send` safety stays off even when you
enable it — the form gets filled and screenshotted (`cej_phase3.png`) but
**not** submitted until you've verified the result and flipped the switch:

```bash
pip install playwright && playwright install chromium
python3 monitor.py --contact-cej "https://udlejning.cej.dk/boliger/<id>"   # dry-run
```

**Use it responsibly.** This submits a real housing application in your name.
Write an honest message, keep it personal, and don't spray inquiries at
apartments you wouldn't actually take — that ruins it for everyone,
including you.

## How it works

No framework, four small modules, ~600 lines total:

```
monitor.py        the loop: poll → diff against seen_listings.json → alert
sources/          one module per site; each exposes parse() + fetch()
filters.py        config-driven price/rooms/size/keyword filtering
notify.py         ntfy push + macOS banner + first-run onboarding
contact_cej.py    optional Playwright form-filler
```

New listings are detected by ID, state survives restarts, network failures
back off exponentially, and every parser is tested offline against recorded
fixtures (`tests/`).

## Roadmap — sites that deserve a module

findbolig.nu · heimstaden.dk · deas.dk · home.dk lejeboliger ·
danskeboligejendomme.dk · lejebolig.dk — or whatever your city hides.
Each one is a ~40-line PR; the template walks you through it.

## Disclaimer

Boligvagten polls publicly available listing pages on your behalf, at a
human-ish pace, for personal use. Respect the sites: keep polling intervals
reasonable, don't run multiple aggressive instances, and check the terms of
service of the sites you enable. This project is not affiliated with any of
the listed sites.

## License

[MIT](LICENSE)
