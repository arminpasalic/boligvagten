# boligvagten 🏠

**Get to Danish housing listings first — rentals *and* for-sale.** Boligvagten
stands watch over Danish housing sites around the clock and pushes an alert to
your phone the minute something new appears — because in Copenhagen, the
difference between getting a viewing and getting nothing is usually measured
in minutes.

*🇩🇰 [Læs denne side på dansk](README.da.md)*

[![CI](https://github.com/arminpasalic/boligvagten/actions/workflows/ci.yml/badge.svg)](https://github.com/arminpasalic/boligvagten/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/boligvagten)](https://pypi.org/project/boligvagten/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)

```
[2026-07-06T19:09:16] 3 new listing(s):
  • [cej] Nordre Fasanvej 119, 2000 Frederiksberg — 1r, 29m², 6.929 DKK/md
    https://udlejning.cej.dk/boliger/f71591e2...
  • [kereby] Valby Langgade 36, 2500 Valby — 3r, 86m², 17.200 DKK/md
    https://kerebyudlejning.dk/bolig/a8ead8ef...
  • [boligsiden] Gunløgsgade 22, 3. 2, 2300 København S — 2r, 47m², 3.975.000 DKK (ejerudgift 3.645 kr./md)
    https://www.boligsiden.dk/adresse/gunloegsgade-22...
```
*…and the same message lands on your phone as a push notification.*

## Why this exists

- **The portals aren't enough.** Everyone watches boligportal.dk. The private
  administrators (CEJ, Kereby, City Apartment, …) list great apartments on
  their own sites where far fewer people are looking — boligvagten watches
  both worlds at once.
- **Buying? Same game.** New for-sale listings (via Boligsiden) reach your
  phone minutes after they go live, not in tomorrow's saved-search email.
- **Speed wins.** Popular listings collect hundreds of inquiries within hours.
  An instant push notification (and optionally an auto-filled contact form,
  see below) puts you at the front of the queue.
- **Zero setup friction.** Pure Python standard library — no accounts, no API
  keys, no database, no dependencies. One command, subscribe to your alert
  channel, done.
- **Built to be forked.** Sources are plug-in modules, filters and cities are
  config, and the parsers are covered by offline tests. Making it watch *your*
  city or *your* favourite site is a small, documented change.

## Quick start

With [uv](https://docs.astral.sh/uv/) (or `pipx install boligvagten`):

```bash
uvx boligvagten
```

Or clone and run — the monitor is pure standard library, so there is no
`pip install` step ([requirements.txt](requirements.txt) exists to say
exactly that):

```bash
git clone https://github.com/arminpasalic/boligvagten.git
cd boligvagten
python3 monitor.py
```

The first run creates your personal `config.py` (in the checkout, or in
`~/.config/boligvagten/` when installed), generates a private notification
channel, and prints exactly what to do:

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
| `boligvagten` | Watch continuously, alert on new listings |
| `boligvagten --list` | One-shot search: print everything matching your filters right now |
| `boligvagten --once` | Run a single check and exit (handy for cron) |
| `boligvagten --test-notify` | Send a test push to every channel |
| `boligvagten --setup` | Re-print the phone setup instructions |
| `boligvagten --contact-cej URL` | Dry-run the CEJ contact form on one listing |

Running from a clone? `python3 monitor.py` takes the same flags.

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
    "description_keywords": ["altan"],   # must appear in the full description
}
```

All keys are optional; besides the above there are `min_price_dkk`,
`max_rooms`, `max_size_m2`, `include_keywords`, and ejerudgift bounds
(`min`/`max_monthly_fee_dkk`) for the for-sale market. Unknown values always
pass — better one alert too many than a silently missed home.

**Another city?** The search URL *is* the search — city, price, size are all
encoded in it. Open the site, set your filters, copy the URL into the source's
config entry. Each entry in [config.example.py](config.example.py) documents
the site-specific trick (Boligportal: just use your city's page, e.g.
`/lejeboliger/aarhus/`; CEJ: append one query param; Boligsiden: edit the
documented API params; …).

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

**Polling pace**: intervals are randomized (default 30–60 s). Be polite —
polling more frequently than the default helps little and risks getting the
affected site's attention.

## Supported sources

| Source | Site | Market | Coverage | How it's read |
|---|---|---|---|---|
| `boligportal` | boligportal.dk | rent | all of Denmark | server-rendered HTML |
| `cej` | udlejning.cej.dk | rent | Zealand / Copenhagen | Remix data endpoint |
| `kereby` | kerebyudlejning.dk | rent | Copenhagen | public JSON API |
| `cityapartment` | cityapartment.dk | rent | Copenhagen | server-rendered HTML |
| `boligsiden` | boligsiden.dk | **sale** | all of Denmark | public JSON API |

Want another site? That's the fun part — see
[CONTRIBUTING.md](CONTRIBUTING.md): copy
[the template](boligvagten/sources/_template.py), write one `parse()`
function, register it, done. PRs welcome — or open a
[site request](https://github.com/arminpasalic/boligvagten/issues/new?template=site_request.yml).

## Auto-contact (CEJ) — optional

CEJ listings receive a flood of inquiries almost immediately. Boligvagten can
fill out CEJ's 3-step contact form automatically the moment a listing
appears: your details, your message to the landlord, your profile.

It is **off by default**, and its `live_send` safety stays off even when you
enable it — the form gets filled and screenshotted (`cej_phase3.png`) but
**not** submitted until you've verified the result and flipped the switch:

```bash
pip install playwright && playwright install chromium
boligvagten --contact-cej "https://udlejning.cej.dk/boliger/<id>"   # dry-run
```

**Use it responsibly.** This submits a real housing application in your name.
Write an honest message, keep it personal, and don't spray inquiries at
apartments you wouldn't actually take — that ruins it for everyone,
including you.

## How it works

No framework, five small modules:

```
boligvagten/monitor.py     the loop: poll → diff against seen_listings.json → alert
boligvagten/sources/       one module per site; each exposes parse() + fetch()
boligvagten/filters.py     config-driven price/rooms/size/keyword filtering
boligvagten/notify.py      ntfy push + macOS banner + first-run onboarding
boligvagten/contact_cej.py optional Playwright form-filler
```

New listings are detected by ID, state is written atomically, failed phone
notifications retry, and CEJ actions use a durable outbox that avoids blind
resubmission after an interrupted run. Network failures back off exponentially,
parser responses are health-checked, and every parser is tested offline against
recorded fixtures (`tests/`).

## Roadmap — sites that deserve a module

findbolig.nu · heimstaden.dk · deas.dk · home.dk lejeboliger ·
danskeboligejendomme.dk · lejebolig.dk — or whatever your city hides.
Each one is a ~40-line PR; the template walks you through it.

## Related projects

- [bolig-ping](https://github.com/saattrupdan/bolig_ping) — for-sale search on
  Boligsiden as a one-shot CLI with email digests; run it from cron if email
  suits you better than push. Boligvagten's Boligsiden support was inspired
  by it.

## Disclaimer

Boligvagten polls publicly available listing pages on your behalf, at a
human-ish pace, for personal use. Respect the sites: keep polling intervals
reasonable, don't run multiple aggressive instances, and check the terms of
service of the sites you enable. This project is not affiliated with any of
the listed sites.

## License

[MIT](LICENSE)
