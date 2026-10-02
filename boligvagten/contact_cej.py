"""CEJ Udlejning: fill in (and optionally send) the contact form on a listing.

The form has three steps — contact details, message, profile — and posts to
CEJ's Remix action /kontakt?_data=routes/contact. The outcome is read from
that response ({"status": "success" | "failed"}) and from the confirmation
CEJ shows ("Din besked er sendt"), never guessed from other page text.

Called through contact.run(), which opens the browser and, for dry runs,
blocks every request that could submit anything.
"""
import re
from urllib.parse import urlsplit

from .contact import CLOSED, FILLED, NOT_SENT, SENT, UNCERTAIN, Result

SUCCESS_TEXT = "Din besked er sendt"
CLOSED_RE = re.compile(
    r"lukket for henvendelser|denne bolig er reserveret|denne bolig er udlejet|"
    r"modtaget tilstr.kkelig mange henvendelser",
    re.I,
)
NEXT_RE = re.compile(r"n.ste", re.I)
SEND_RE = re.compile(r"^\s*send\s*$", re.I)
ACCEPT_RE = re.compile(r"^\s*accepter\s*$", re.I)


def owns_host(host):
    return host == "cej.dk" or host.endswith(".cej.dk")


def allow_in_dry_run(request):
    """Only the cookie-consent POST; CEJ's app crashes when that one fails."""
    parts = urlsplit(request.url)
    return parts.path == "/" and (request.post_data or "").strip() == "marketingAccepted=true"


def is_submit(request):
    return request.method == "POST" and urlsplit(request.url).path.rstrip("/") == "/kontakt"


def _visible(locator, timeout):
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def _form_errors(page):
    try:
        texts = page.locator("form [class*='error']").all_inner_texts()
    except Exception:
        return ""
    return "; ".join(t.strip() for t in texts if t.strip())[:200]


def _pick_tile(page, heading, label):
    # Tiles are <div class="cursor-pointer"> inside the section whose <h4>
    # contains the heading (the real one reads e.g. "Hvem er du / I?").
    section = page.locator("div.w-full", has=page.locator(f'h4:has-text("{heading}")')).first
    section.locator("div.cursor-pointer", has_text=label).first.click()


def contact(page, listing_url, listing_id, cc, live, screenshot):
    # The cookie banner can appear seconds after load and then blocks every
    # click; this handler dismisses it whenever it shows up.
    page.add_locator_handler(page.get_by_role("button", name=ACCEPT_RE), lambda b: b.click())
    page.goto(listing_url, wait_until="domcontentloaded")

    name = page.locator("#input-name")
    if not _visible(name, 10000):
        # Older layout: the form sits behind a "Kontakt" button.
        try:
            page.locator("button, a").filter(
                has_text=re.compile(r"^\s*Kontakt\s*$")
            ).first.click(timeout=3000)
        except Exception:
            pass
    if not _visible(name, 4000):
        if CLOSED_RE.search(page.inner_text("body")):
            return Result(CLOSED, "the listing is closed for inquiries")
        return Result(NOT_SENT, "contact form not found on the page")

    # Step 1: contact details.
    name.fill(cc["name"])
    page.locator("#input-email").fill(cc["email"])
    page.locator("#input-phone").fill(cc["phone"])
    page.get_by_role("button", name=NEXT_RE).click()
    message = page.locator("textarea")
    if not _visible(message, 10000):
        return Result(NOT_SENT, f"step 1 was not accepted {_form_errors(page)}".strip())

    # Step 2: message to the landlord.
    message.first.fill(cc["message"])
    page.get_by_role("button", name=NEXT_RE).click()
    birthdate = page.locator("#input-birthDate")
    if not _visible(birthdate, 10000):
        return Result(NOT_SENT, f"step 2 was not accepted {_form_errors(page)}".strip())

    # Step 3: profile.
    if cc.get("birthdate"):
        birthdate.fill(cc["birthdate"])
    if cc.get("hvem"):
        _pick_tile(page, "Hvem er du", cc["hvem"])
    if cc.get("beskaeftigelse"):
        _pick_tile(page, "Beskæftigelse", cc["beskaeftigelse"])
    for detail in cc.get("detaljer") or []:
        _pick_tile(page, "Detaljer", detail)

    send = page.get_by_role("button", name=SEND_RE)
    if not _visible(send, 5000):
        return Result(NOT_SENT, "the Send button is missing")
    try:
        form = page.locator("form").filter(has=send).first
        form.scroll_into_view_if_needed(timeout=2000)
        form.screenshot(path=str(screenshot))
    except Exception:
        page.screenshot(path=str(screenshot), full_page=True)

    if not live:
        return Result(FILLED, f"form filled, not sent (screenshot: {screenshot})")

    # Everything below may have reached CEJ: no outcome here is retried
    # unless CEJ itself said the message was not saved.
    try:
        with page.expect_response(lambda r: is_submit(r.request), timeout=30000) as info:
            send.first.click()
        response = info.value
    except Exception as e:
        return Result(UNCERTAIN, f"pressed Send but got no reply: {type(e).__name__}")
    try:
        data = response.json()
    except Exception:
        data = None
    status = data.get("status") if isinstance(data, dict) else None
    if response.ok and status == "success":
        confirmed = _visible(page.get_by_text(SUCCESS_TEXT), 5000)
        return Result(SENT, "CEJ confirmed: Din besked er sendt" if confirmed
                      else "CEJ accepted the message")
    if response.ok and status == "failed":
        return Result(NOT_SENT, "CEJ answered 'Der er sket en fejl'; nothing was saved")
    if response.ok and isinstance(data, dict) and data.get("errors"):
        return Result(NOT_SENT, f"CEJ rejected the form: {data['errors']}")
    return Result(UNCERTAIN, f"unexpected reply: HTTP {response.status} {str(data)[:200]}")
