"""Auto-fill the contact ("Kontakt") form on a CEJ listing page — optional feature.

CEJ listings get hundreds of inquiries within hours; answering first matters.
When enabled in config (CEJ_CONTACT), every new CEJ listing triggers this
3-phase form fill: contact details → message to landlord → profile tiles.

Safety defaults: disabled, and even when enabled `live_send=False` fills the
form but does NOT click Send — a screenshot (cej_phase3.png) is saved so you
can verify everything looks right before going live.

Requires Playwright (the only non-stdlib dependency in this project):
    pip install playwright && playwright install chromium
"""
import re

from . import paths

SCREENSHOT = paths.state_dir() / "cej_phase3.png"


def contact(listing_url, cc):
    """Fill (and optionally submit) the contact form. `cc` is the CEJ_CONTACT dict."""
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "[cej] auto-contact needs Playwright:\n"
            "      pip install playwright && playwright install chromium",
            flush=True,
        )
        return

    live = bool(cc["live_send"])
    headless = bool(cc["headless"])
    print(f"[cej] contacting {listing_url} (live={live}, headless={headless})", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(listing_url, wait_until="domcontentloaded")

            # Dismiss cookie banner if present.
            try:
                page.get_by_role(
                    "button", name=re.compile(r"accepter", re.I)
                ).first.click(timeout=5000)
            except Exception:
                pass

            # Phase 1: newer CEJ pages embed the contact form directly in the
            # page; older ones hid it behind a "Kontakt" button. Popular
            # listings close ("Lukket for henvendelser" / "Reserveret") and
            # have neither — detect that and skip instead of timing out.
            if not _form_visible(page, timeout=4000):
                try:
                    page.get_by_role(
                        "button", name=re.compile(r"kontakt", re.I)
                    ).first.click(timeout=4000)
                except Exception:
                    # Trigger may be a link, not a button. Exact-match the text
                    # so we never grab the footer ("Kontakt bolig@cej.dk").
                    try:
                        page.locator("button, a").filter(
                            has_text=re.compile(r"^\s*Kontakt\s*$")
                        ).first.click(timeout=2000)
                    except Exception:
                        pass
            if not _form_visible(page, timeout=4000):
                body = page.inner_text("body")
                if re.search(r"lukket for henvendelser|reserveret", body, re.I):
                    print(
                        f"[cej] listing is closed/reserved for inquiries — skipping: "
                        f"{listing_url}",
                        flush=True,
                    )
                else:
                    print(
                        f"[cej] contact form not found (layout changed?) — skipping: "
                        f"{listing_url}",
                        flush=True,
                    )
                return

            page.locator("#input-name").fill(cc["name"])
            page.locator("#input-email").fill(cc["email"])
            page.locator("#input-phone").fill(cc["phone"])
            page.get_by_role("button", name=re.compile(r"n.ste", re.I)).click()

            # Phase 2: message textarea.
            page.locator("textarea").first.fill(cc["message"])
            page.get_by_role("button", name=re.compile(r"n.ste", re.I)).click()

            # Phase 3: birthdate + tile selections.
            page.locator("#input-birthDate").fill(cc["birthdate"])
            _pick_tile(page, "Hvem er du", cc["hvem"])
            _pick_tile(page, "Beskæftigelse", cc["beskaeftigelse"])
            for d in cc["detaljer"]:
                _pick_tile(page, "Detaljer", d)

            # Try to capture just the modal/form panel for a readable shot.
            panel = page.locator("form").first
            try:
                panel.scroll_into_view_if_needed(timeout=2000)
                panel.screenshot(path=str(SCREENSHOT))
            except Exception:
                page.screenshot(path=str(SCREENSHOT), full_page=True)
            print(f"[cej] phase-3 screenshot saved to {SCREENSHOT}", flush=True)

            if live:
                page.get_by_role("button", name=re.compile(r"^send$", re.I)).click()
                page.wait_for_selector(
                    "text=/tak|modtaget|success/i", timeout=15000
                )
                print(f"[cej] SENT for {listing_url}", flush=True)
            else:
                print(
                    "[cej] DRY-RUN: form filled through phase 3 but NOT submitted. "
                    "Set CEJ_CONTACT['live_send'] = True in config.py to actually send.",
                    flush=True,
                )
                # Keep the browser open briefly when not headless so you can look.
                if not headless:
                    page.wait_for_timeout(20000)
        except PWTimeout as e:
            print(f"[cej] timed out on {listing_url}: {e}", flush=True)
        except Exception as e:
            print(f"[cej] contact failed for {listing_url}: {e}", flush=True)
        finally:
            browser.close()


def _form_visible(page, timeout=1500):
    """True once the contact form's first field is on screen."""
    try:
        page.locator("#input-name").first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def _pick_tile(page, section_heading_substr, label):
    # The tiles are <div class="cursor-pointer"> under a section whose <h4>
    # contains section_heading_substr. Match by partial heading text (the
    # real heading is e.g. "Hvem er du / I?") and pick the tile by label.
    section = page.locator(
        "div.w-full",
        has=page.locator(f'h4:has-text("{section_heading_substr}")'),
    ).first
    tile = section.locator("div.cursor-pointer", has_text=label).first
    tile.click()
