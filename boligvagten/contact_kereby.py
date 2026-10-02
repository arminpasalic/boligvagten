"""Kereby: fill in (and optionally send) the "Interesseret?" form on a listing.

The form (name, email, message, privacy consent) posts JSON to
/wp-json/jorato-templates/v1/contact. Kereby's own script treats 2xx as
sent, 4xx as a rejected form (with a message) and 5xx as a server failure;
the outcome here is read from that same response.

Listing pages are published on kereby.dk shortly after a listing appears
in the API. Until then contact returns NOT_READY and is retried later. The
page is checked to carry the listing's id before anything is filled in.

Called through contact.run(), which opens the browser and, for dry runs,
blocks every request that could submit anything.
"""
import re
from urllib.parse import urlsplit

from .contact import CLOSED, FILLED, NOT_READY, NOT_SENT, SENT, UNCERTAIN, Result
from .sources import kereby

SUCCESS_TEXT = "Beskeden er sendt"
CONTACT_PATH = "/wp-json/jorato-templates/v1/contact"
CLOSED_RE = re.compile(r"\b(udlejet|reserveret)\b", re.I)


def owns_host(host):
    return host in ("kereby.dk", "www.kereby.dk", "kerebyudlejning.dk")


def allow_in_dry_run(request):
    return False  # nothing on kereby.dk needs a POST before the form is sent


def is_submit(request):
    return request.method == "POST" and urlsplit(request.url).path.rstrip("/") == CONTACT_PATH


def _is_listing_page(url):
    parts = urlsplit(url)
    return parts.hostname == "kereby.dk" and re.fullmatch(r"/bolig/[a-z0-9-]+/?", parts.path or "")


def contact(page, listing_url, listing_id, cc, live, screenshot):
    # listing_id is None for a hand-picked page (--contact-test URL): no id check.
    tenancy_id = listing_id.split(":", 1)[-1] if listing_id else None
    if not _is_listing_page(listing_url):
        if not tenancy_id:
            return Result(NOT_SENT, "not a kereby.dk/bolig/... listing page")
        try:
            listing_url = kereby.resolve_page_url(tenancy_id)
        except Exception as e:
            return Result(NOT_READY, f"could not look up the listing page: {e}")
        if not listing_url:
            return Result(NOT_READY, "Kereby has not published the listing page yet")

    # A newsletter pop-up can open over the page; close it whenever it does.
    page.add_locator_handler(
        page.locator(".newsletter-modal__dialog"),
        lambda _: page.locator(".newsletter-modal__close").first.click(),
    )
    page.goto(listing_url, wait_until="domcontentloaded")
    if tenancy_id and tenancy_id not in page.content():
        return Result(NOT_READY, f"{listing_url} is not this listing's page (yet)")

    form = page.locator("form[data-jorato-contact-form]:visible").first
    try:
        form.wait_for(state="visible", timeout=10000)
    except Exception:
        if CLOSED_RE.search(page.inner_text("body")):
            return Result(CLOSED, "the listing is no longer available")
        return Result(NOT_SENT, "contact form not found on the page")

    form.locator("input[name=name]").fill(cc["name"])
    form.locator("input[name=email]").fill(cc["email"])
    form.locator("textarea[name=message]").fill(cc["message"])
    form.locator("input[name=privacy]").check()
    # The hidden "website" field is a bot trap and must stay empty.

    submit = form.locator("[data-jorato-contact-submit]")
    try:
        page.wait_for_function("el => !el.disabled", arg=submit.element_handle(), timeout=5000)
    except Exception:
        error = form.locator("[data-jorato-contact-error]").inner_text().strip()
        return Result(NOT_SENT, f"the form was not accepted {error}".strip())
    try:
        form.scroll_into_view_if_needed(timeout=2000)
        form.screenshot(path=str(screenshot))
    except Exception:
        page.screenshot(path=str(screenshot), full_page=True)

    if not live:
        return Result(FILLED, f"form filled, not sent (screenshot: {screenshot})")

    # Everything below may have reached Kereby: only an explicit rejection
    # (4xx: Kereby's form validation) counts as "not sent".
    try:
        with page.expect_response(lambda r: is_submit(r.request), timeout=30000) as info:
            submit.click()
        response = info.value
    except Exception as e:
        return Result(UNCERTAIN, f"pressed Send but got no reply: {type(e).__name__}")
    try:
        data = response.json()
    except Exception:
        data = None
    message = data.get("message") if isinstance(data, dict) else None
    if 200 <= response.status < 300:
        try:  # shown for only ~2 s before the form resets
            page.get_by_text(SUCCESS_TEXT).first.wait_for(state="visible", timeout=1500)
            confirmed = True
        except Exception:
            confirmed = False
        return Result(SENT, "Kereby confirmed: Beskeden er sendt" if confirmed
                      else "Kereby accepted the message")
    if 400 <= response.status < 500:
        return Result(NOT_SENT, f"Kereby rejected the form: {message or response.status}")
    return Result(UNCERTAIN, f"Kereby server error HTTP {response.status}: {message or ''}".strip())
