"""
Wolt pizza-price scraper (5th site).

Wolt is a delivery *aggregator*, not a pizzeria, so there is no single "Wolt
pizza price". This scraper tracks ONE specific Wolt venue (restaurant) that you
choose, and extracts the same three comparison price points as the other
chains:
    family      – cheapest family/large pizza
    meal_single – cheapest single-pizza meal deal
    meal_double – cheapest two-pizza meal deal

Wolt shows a single price (no pickup/delivery split at the menu level), so the
result is stored under `dlv` and `pu` is left empty — consistent with how the
dashboard treats single-price sites.

Configuration (env vars, so it works both locally and on GitHub Actions):
    WOLT_VENUE_URL   full URL of the Wolt venue menu page to track, e.g.
                     https://wolt.com/he/isr/tel-aviv/restaurant/<slug>
    WOLT_ADDRESS     (optional) delivery address to set, default Tel Aviv ref.

Wolt's old public REST API (restaurant-api.wolt.com/v1) now returns 430/429, so
we drive a real browser and intercept the menu JSON the page itself requests
from consumer-api.wolt.com. Anti-bot pages (Cloudflare / queue) are DETECTED
and reported as a failure for this site only — never bypassed.
"""

import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# reuse the shared classification helpers from the main scraper
from multi_scraper import (
    classify_prices, pick_price, UA, TLV_ADDRESS,
    _empty_prices, kw_match, FAMILY_KW, MEAL_KW, SINGLE_KW, DOUBLE_KW,
)

DEBUG_DIR = Path(__file__).parent / "data"
STEALTH_JS = ("Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); "
              "window.chrome={runtime:{}};")

# Signs that Wolt served an anti-bot / verification page instead of the venue.
BLOCK_MARKERS = [
    "verifying you are human", "just a moment", "cf-challenge", "cloudflare",
    "attention required", "אימות", "רובוט", "queue-it", "please verify",
]


def _normalize_price(v):
    """Wolt embeds prices as integer minor units (agorot): 6900 -> 69.0."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        p = float(v)
    else:
        m = re.search(r"\d+(?:\.\d{1,2})?", str(v).replace(",", ""))
        if not m:
            return None
        p = float(m.group())
    # Menu API values are in agorot; convert when clearly too large.
    if p > 800:
        p = round(p / 100, 2)
    return p if 10 < p < 800 else None


def _extract_items(obj, out=None):
    """
    Walk Wolt menu JSON collecting (name, price) pairs. Wolt item objects look
    like {"name": "...", "baseprice": 6900, ...} or {"name","price"} depending
    on the endpoint, so we accept several price keys.
    """
    if out is None:
        out = []
    PRICE_KEYS = ("baseprice", "base_price", "price", "unit_price")
    if isinstance(obj, dict):
        name = obj.get("name") or obj.get("title")
        price = None
        for k in PRICE_KEYS:
            if k in obj and obj[k] is not None:
                price = obj[k]
                break
        if isinstance(name, dict):  # localized {"lang":"...","value":"..."}
            name = name.get("value") or name.get("he") or next(iter(name.values()), "")
        if name and price is not None:
            np = _normalize_price(price)
            if np is not None:
                out.append((np, str(name)))
        for v in obj.values():
            _extract_items(v, out)
    elif isinstance(obj, list):
        for it in obj:
            _extract_items(it, out)
    return out


def scrape_wolt(pw=None, venue_url=None, verbose=True):
    """
    Scrape one Wolt venue. Returns the standard chain dict:
        {"pu": {...}, "dlv": {...}, "error": <str|None>}
    """
    venue_url = venue_url or os.environ.get("WOLT_VENUE_URL", "").strip()
    r = {"pu": _empty_prices(), "dlv": _empty_prices(), "error": None}

    if not venue_url:
        r["error"] = "לא הוגדר WOLT_VENUE_URL (יש לבחור מסעדה ספציפית בוולט)"
        if verbose:
            print(f"    [WOLT] skipped: {r['error']}")
        return r

    owns_pw = pw is None
    if owns_pw:
        pw = sync_playwright().start()

    menu_blobs = []

    def on_response(resp):
        try:
            url = resp.url
            if "wolt.com" in url and any(k in url.lower()
                                         for k in ("assortment", "menu", "venue")):
                ct = (resp.headers or {}).get("content-type", "")
                if "application/json" in ct:
                    menu_blobs.append(resp.json())
        except Exception:
            pass

    browser = ctx = page = None
    try:
        browser = pw.chromium.launch(
            channel="chrome", headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            locale="he-IL", timezone_id="Asia/Jerusalem",
            viewport={"width": 1440, "height": 900}, user_agent=UA,
            extra_http_headers={"Accept-Language": "he-IL,he;q=0.9"},
        )
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()
        page.on("response", on_response)

        last_err = None
        for attempt in range(3):  # retry with backoff
            try:
                page.goto(venue_url, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(4000 + attempt * 2000)

                body_text = (page.inner_text("body") or "").lower()
                if any(m in body_text for m in BLOCK_MARKERS) and not menu_blobs:
                    r["error"] = "האתר חסם גישה אוטומטית — נדרשת בדיקה ידנית"
                    _screenshot(page, "wolt_blocked")
                    if verbose:
                        print(f"    [WOLT] blocked (attempt {attempt+1})")
                    time.sleep(3 * (attempt + 1))
                    continue

                # Nudge lazy-loaded menu sections into view.
                for _ in range(6):
                    page.mouse.wheel(0, 1600)
                    page.wait_for_timeout(700)

                if menu_blobs:
                    break
                last_err = "menu JSON not captured"
                time.sleep(2 * (attempt + 1))
            except PWTimeout as e:
                last_err = f"timeout: {str(e)[:80]}"
                time.sleep(3 * (attempt + 1))
            except Exception as e:
                last_err = str(e)[:100]
                time.sleep(2 * (attempt + 1))

        # Parse whatever menu JSON we captured.
        pairs = []
        for blob in menu_blobs:
            pairs.extend(_extract_items(blob))

        # Fallback: parse the rendered DOM if no JSON was intercepted.
        if not pairs:
            pairs = _parse_dom(page)

        if pairs:
            r["dlv"].update(classify_prices(pairs))
            if verbose:
                print(f"    [WOLT] parsed {len(pairs)} items → {r['dlv']}")
            if all(v is None for v in r["dlv"].values()):
                r["error"] = "מחירים נמצאו אך לא סווגו לקטגוריות (בדוק מיפוי)"
        elif not r["error"]:
            r["error"] = last_err or "לא נמצאו מחירים בעמוד"
            _screenshot(page, "wolt_nomenu")

    except Exception as e:
        r["error"] = str(e)[:120]
        if page:
            _screenshot(page, "wolt_error")
    finally:
        if browser:
            browser.close()
        if owns_pw:
            pw.stop()

    return r


def _parse_dom(page):
    """Best-effort DOM fallback: grab (name, price) from menu item cards."""
    try:
        items = page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('[data-test-id*="menu-item"], [class*="MenuItem"], article, li').forEach(el => {
                const t = (el.innerText || '').trim();
                if (t && /\\d/.test(t) && t.length < 200) out.push(t);
            });
            return out;
        }""")
        pairs = []
        for line in items or []:
            p = _normalize_price(line)
            if p is not None:
                pairs.append((p, line))
        return pairs
    except Exception:
        return []


def _screenshot(page, name):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"))
    except Exception:
        pass


if __name__ == "__main__":
    res = scrape_wolt()
    print("\nWolt result:", res)
