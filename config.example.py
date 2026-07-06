"""Boligvagten configuration.

On first run this file is copied to config.py — that copy is yours (and
gitignored, since it will hold your ntfy topic and, if you enable
auto-contact, your personal details). Edit values freely; no other files
need changes for typical tweaks.
"""

# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------
# Seconds between checks. Each interval is randomized in [MIN, MAX] so the
# traffic pattern looks human. 60–180s is fast enough to be among the first
# for nearly every listing while staying polite to the sites. You can lower
# it, but be reasonable — hammering the sites helps nobody.
POLL_MIN_SECONDS = 60
POLL_MAX_SECONDS = 180

# When every source fails (you're probably offline), back off exponentially
# up to this many seconds between retries.
OFFLINE_MAX_BACKOFF = 600

# ---------------------------------------------------------------------------
# Filters — applied to every listing from every source.
# ---------------------------------------------------------------------------
# All keys optional (None/empty = off). Listings with unknown values pass the
# numeric bounds: better one alert too many than a silently missed apartment.
# Tip: price bounds apply to whatever the source's price is — monthly rent
# for rental sources, cash price for for-sale sources. Mixing both markets?
# Put price bounds in each source's own "filters" dict instead of here.
FILTERS = {
    "max_price_dkk": None,          # e.g. 14000
    "min_price_dkk": None,          # e.g. 4000 — weeds out too-good-to-be-true ads
    "min_rooms": None,              # e.g. 2
    "max_rooms": None,              # e.g. 4
    "min_size_m2": None,            # e.g. 50
    "max_size_m2": None,            # e.g. 120
    "min_monthly_fee_dkk": None,    # ejerudgift bounds — for-sale listings only
    "max_monthly_fee_dkk": None,    # e.g. 5000
    # Case-insensitive match on name + address (+ description when the
    # source provides one):
    "exclude_keywords": [],         # e.g. ["studiebolig", "delevenlig", "ballerup"]
    "include_keywords": [],         # keep only matches, e.g. ["altan", "terrasse"]
}

# ---------------------------------------------------------------------------
# Sources — toggle and configure each site here.
#
# The URL *is* the search: city, price range, size — everything is encoded in
# it. For each site: open it in a browser, set your filters, copy the URL
# from the address bar, paste it below (CEJ needs one extra param, see note).
# Want several searches/cities at once? Use  "urls": [url1, url2]  instead.
# Each source can also carry its own "filters" dict (same keys as FILTERS).
# ---------------------------------------------------------------------------
SOURCES = {
    # CEJ (udlejning.cej.dk) — one of the biggest private administrators,
    # Zealand/Copenhagen. Getting your URL: set your filters on
    # https://udlejning.cej.dk/find-bolig/overblik (price, region, ...),
    # copy the URL and append  &_data=routes%2Fsearch%2Flayout
    # — that makes the server return the raw listing data (Remix loader).
    "cej": {
        "enabled": True,
        "url": (
            "https://udlejning.cej.dk/find-bolig/overblik"
            "?collection=residences&monthlyPrice=0-14000&p=sj%C3%A6lland"
            "&_data=routes%2Fsearch%2Flayout"
        ),
        # CEJ mixes dedicated student housing into the results; drop it unless
        # that's what you're after.
        "filters": {
            "exclude_keywords": ["studiebolig", "studerende", "student"],
        },
    },

    # City Apartment (cityapartment.dk) — private administrator, Copenhagen.
    # Getting your URL: set price/size on
    # https://cityapartment.dk/apartment-rentals-copenhagen/ and copy the URL
    # (your filters land in the _sfm_* query params).
    "cityapartment": {
        "enabled": True,
        "url": (
            "https://cityapartment.dk/apartment-rentals-copenhagen/"
            "?_sfm_pris=0+14000&_sfm_ikon_m2=0+300"
        ),
    },

    # Boligportal (boligportal.dk) — Denmark's biggest rental portal.
    # Getting your URL: open your city page, e.g.
    # https://www.boligportal.dk/lejeboliger/københavn/ (or /aarhus/, /odense/,
    # ...), add filters on the site, copy the URL.
    "boligportal": {
        "enabled": True,
        "url": "https://www.boligportal.dk/lejeboliger/k%C3%B8benhavn/?min_rental_period=0",
    },

    # Kereby (kerebyudlejning.dk) — private administrator, Copenhagen.
    # This talks directly to their public listing API (found via DevTools →
    # Network), so there is no URL to customize — use "filters" instead.
    "kereby": {
        "enabled": True,
        "url": (
            "https://api.jorato.com/tenancies"
            "?visibility=public&showAll=true&key=2gXoBtKvFMMgKJ1VBJ5G5pNr2GD"
        ),
        "filters": {
            "max_price_dkk": 20000,   # Kereby skews expensive
        },
    },
}

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
# Phone push via https://ntfy.sh — free, no account needed. A random topic is
# generated on first run; install the ntfy app and subscribe to that topic
# (run `python3 monitor.py --setup` to see the instructions again).
# Self-hosting ntfy? Point "server" at your instance.
NTFY = {
    "enabled": True,
    "server": "https://ntfy.sh",
    "topic": "",  # auto-generated on first run — keep it secret
}

# macOS desktop banner (osascript). Harmless on other OSes (no-op).
MACOS_NOTIFICATION = True

# ---------------------------------------------------------------------------
# CEJ auto-contact (optional; needs Playwright)
# ---------------------------------------------------------------------------
# Popular listings get flooded with inquiries within the hour — being among
# the very first is what gets you a viewing. When enabled, every new CEJ
# listing triggers an automatic fill of its 3-step contact form.
#
#   pip install playwright && playwright install chromium
#
# SAFETY: auto_contact is off by default, and live_send=False means the form
# is filled but NOT submitted — a screenshot (cej_phase3.png) is saved so you
# can check it. Try it on one listing first:
#   python3 monitor.py --contact-cej "https://udlejning.cej.dk/boliger/..."
# Only flip live_send once the screenshot looks right. This sends a real
# application in your name — use it responsibly.
CEJ_CONTACT = {
    "auto_contact": False,   # True → auto-fill the form on every new CEJ listing
    "live_send": False,      # False → dry-run: fill everything but don't press Send
    "headless": True,        # False → watch the browser while it fills

    # Step 1 — contact details
    "name": "Your Name",
    "email": "you@example.com",
    "phone": "12345678",

    # Step 2 — free-text message to the landlord. Sell yourself: job, income
    # (documentable), non-smoker, how fast you can move in, ...
    "message": """Hej,

Jeg hedder <navn>, er <alder> år og søger en fast bolig. Jeg er i fast
fuldtidsarbejde som <stilling> og kan dokumentere min indkomst med lønsedler.

Jeg er klar til fremvisning med kort varsel og kan overtage hurtigt.

Tlf: <telefon> — email: <email>

Med venlig hilsen
<navn>""",

    # Step 3 — profile
    "birthdate": "1990-01-01",      # ISO yyyy-mm-dd
    "hvem": "Enkeltperson",         # Enkeltperson / Par/kærester / Familie / Gruppe/roomies
    "beskaeftigelse": "I arbejde",  # I arbejde / Studerende / Ledig / Pensioneret
    "detaljer": [],                 # e.g. ["Har kæledyr"] — empty list to skip
}
