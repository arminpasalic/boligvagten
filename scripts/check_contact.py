"""Check auto-contact against the live sites without ever sending anything.

    python scripts/check_contact.py            # both sites
    python scripts/check_contact.py cej        # one site

For each site it picks a current listing and runs:
  1. a dry run (fills the form, takes a screenshot);
  2. the full "send" path three times, with the site's reply faked in the
     browser: success, a rejection, and a server error. The real submit
     request is answered locally and never reaches the site.

Uses made-up contact details. Run it after a site redesign: if a form step
or the reply handling broke, this shows which one. Needs Playwright.
"""
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from boligvagten import contact  # noqa: E402
from boligvagten.sources import cej, kereby  # noqa: E402

TEST_DETAILS = contact.normalize({
    "name": "Test Testesen",
    "email": "test@example.invalid",
    "phone": "20304050",
    "message": "Automatisk test af formularen - ignorer venligst.",
    "birthdate": "1990-01-01",
    "hvem": "Enkeltperson",
    "beskaeftigelse": "I arbejde",
})

# (label, HTTP status, JSON body, expected result code)
FAKES = {
    "cej": [
        ("success", 200, {"status": "success"}, contact.SENT),
        ("site error", 200, {"status": "failed"}, contact.NOT_SENT),
        ("server crash", 500, {"message": "boom"}, contact.UNCERTAIN),
    ],
    "kereby": [
        ("success", 200, {"success": True}, contact.SENT),
        ("rejected", 400, {"message": "Ugyldig email"}, contact.NOT_SENT),
        ("server crash", 500, {"message": "boom"}, contact.UNCERTAIN),
    ],
}


def faking_route(site, status, body, seen):
    module = contact.module_for(site)

    def route(r, request):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return r.continue_()
        host = urlsplit(request.url).hostname or ""
        if not module.owns_host(host):
            return r.abort()
        if module.is_submit(request):
            seen.append(request.post_data)
            return r.fulfill(status=status, content_type="application/json",
                             body=json.dumps(body))
        if module.allow_in_dry_run(request):
            return r.continue_()
        return r.abort()
    return route


def listings(site):
    if site == "cej":
        conf = {"url": "https://udlejning.cej.dk/find-bolig/overblik?collection=residences"
                       "&p=sj%C3%A6lland&_data=routes%2Fsearch%2Flayout"}
        return cej.fetch(conf)
    return kereby.fetch({"url": kereby.DEFAULT_URL})


def check(site, out_dir):
    ok = True
    print(f"\n== {site}")
    candidates = listings(site)
    if not candidates:
        print("   no listings right now — nothing to test")
        return True
    for listing in candidates[:5]:
        result = contact.run(site, listing.url, listing.id, TEST_DETAILS, live=False,
                             screenshot=out_dir / f"{site}-dry.png")
        if result.code != contact.CLOSED:
            break
    print(f"   dry run on {listing.url}: {result.code} — {result.detail}")
    ok &= result.code == contact.FILLED

    for label, status, body, expected in FAKES[site]:
        seen = []
        result = contact.run(site, listing.url, listing.id, TEST_DETAILS, live=True,
                             screenshot=out_dir / f"{site}-{status}.png",
                             route=faking_route(site, status, body, seen))
        passed = result.code == expected and len(seen) == 1
        ok &= passed
        print(f"   fake {label:<12} -> {result.code:<10} "
              f"{'ok' if passed else f'EXPECTED {expected}'} ({result.detail})")
        if seen and label == "success":
            print(f"   submitted payload: {seen[0][:300]}")
    return ok


def main(argv):
    sites = argv or list(contact.SITES)
    out_dir = Path(tempfile.mkdtemp(prefix="boligvagten-check-"))
    ok = all([check(site, out_dir) for site in sites])
    print(f"\nScreenshots: {out_dir}")
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
