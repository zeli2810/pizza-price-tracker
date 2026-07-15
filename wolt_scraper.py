"""
Wolt pizza-discovery scraper.

Loads the Wolt "pizza" category discovery page for a Tel Aviv location and
extracts the RANKED list of pizza venues (sort_by=recommended). Each venue is
mapped to the SAME record shape as the Pais Plus offers, so the dashboard's
Wolt tab can mirror the Pais Plus tab (offers table + daily score matrix +
cumulative history), with the same row-based scoring.

Location: Wolt honours a geolocation override, so we set the browser location
to central Tel Aviv (Dizengoff area) — no manual address entry needed.

Like Pais Plus, this may only work from an Israeli IP (Wolt geo-detects); on a
US CI runner it may be blocked. Detected blocks are reported, not bypassed.

Output: data/wolt_offers.json (history) + Firestore wolt_offers/{date}.
"""

import json
import re
import time
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from multi_scraper import UA  # also sets UTF-8 stdout on Windows

DATA_FILE = Path(__file__).parent / "data" / "wolt_offers.json"
SHOT_DIR = Path(__file__).parent / "data"

DISCOVERY_URL = (
    "https://wolt.com/he/discovery/stores/category/pizza"
    "?rootCategory=%7B%22name%22%3A%22%D7%9E%D7%A1%D7%A2%D7%93%D7%95%D7%AA%22%2C%22slug%22%3A%22restaurants%22%7D"
    "&subCategoryPath=%5B%7B%22name%22%3A%22%D7%A4%D7%99%D7%A6%D7%94%22%2C%22slug%22%3A%22pizza%22%7D%5D"
    "&sort_by=recommended"
)
# Central Tel Aviv (Dizengoff area) — the reference location.
TLV_LAT, TLV_LON = 32.0809, 34.7806

BLOCK_MARKERS = ["just a moment", "cloudflare", "attention required", "verifying you are human"]

# JS that returns one object per venue card: href, y (for row clustering), lines.
_EXTRACT_JS = r"""
() => {
  const seen = new Set();
  const out = [];
  document.querySelectorAll('a[href*="/restaurant/"]').forEach(a => {
    const href = a.getAttribute('href') || '';
    // Israel only — Wolt venue links are /he/isr/<city>/restaurant/... ; a
    // foreign (e.g. US) result from a wrong-IP run won't contain "/isr/".
    if (!href.includes('/isr/')) return;
    const slug = href.split('/restaurant/')[1] || href;
    if (seen.has(slug)) return;
    seen.add(slug);
    const card = a.closest('[data-test-id]') || a;
    const rect = card.getBoundingClientRect();
    const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    out.push({ slug, href, y: Math.round(rect.top + window.scrollY), lines });
  });
  return out;
}
"""


def _parse_card(c):
    """Map a raw card {slug, href, y, lines} to a Pais-Plus-shaped offer."""
    lines = c.get("lines", [])
    name = lines[0] if lines else ""
    rating = fee = promo = None
    items = []
    for l in lines[1:]:
        if "מחיר:" in l:
            m = re.search(r"(\d+(?:\.\d+)?)", l.split("מחיר:")[-1])
            if m:
                items.append((float(m.group(1)), l.split("מחיר:")[0].strip()))
        elif re.fullmatch(r"\d(?:\.\d)?", l):        # rating e.g. 9.0 / 8
            rating = l
        elif re.fullmatch(r"[\d.]+\s*₪", l):          # delivery fee e.g. "0.00 ₪"
            fee = l
        elif ("הנחה" in l) or ("הטבה" in l) or ("%" in l):
            promo = l
    cheapest = min(items, key=lambda x: x[0]) if items else (None, "")
    price_value, cheapest_item = cheapest
    offer_text = promo or cheapest_item or name
    return {
        "slug": c.get("slug"),
        "name": name,
        "rating": rating,
        "delivery_fee": fee,
        "promo": promo,
        "price_value": price_value,
        "cheapest_item": cheapest_item,
        "product_url": ("https://wolt.com" + c["href"]) if c.get("href", "").startswith("/") else c.get("href"),
        "is_preferred": bool(promo),
        "y": c.get("y", 0),
    }


def run_scrape(verbose=True):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    offers = []
    error = None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome", headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(
            locale="he-IL", timezone_id="Asia/Jerusalem", viewport={"width": 1440, "height": 1000},
            user_agent=UA, geolocation={"latitude": TLV_LAT, "longitude": TLV_LON},
            permissions=["geolocation"])
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()
        raw = []
        try:
            for attempt in range(3):
                page.goto(DISCOVERY_URL, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(6000 + attempt * 2000)
                body = (page.inner_text("body") or "").lower()
                if any(m in body for m in BLOCK_MARKERS):
                    error = "האתר חסם גישה אוטומטית — נדרשת בדיקה ידנית"
                    _shot(page, "wolt_blocked")
                    time.sleep(3 * (attempt + 1)); continue
                # The list lazy-loads / virtualizes, so accumulate cards by slug
                # across scroll steps (first sighting keeps its absolute Y).
                acc = {}
                stagnant = 0
                for _ in range(120):
                    for c in page.evaluate(_EXTRACT_JS):
                        if c["slug"] not in acc:
                            acc[c["slug"]] = c
                    before = len(acc)
                    page.mouse.wheel(0, 1400)
                    page.wait_for_timeout(650)
                    for c in page.evaluate(_EXTRACT_JS):
                        if c["slug"] not in acc:
                            acc[c["slug"]] = c
                    stagnant = stagnant + 1 if len(acc) == before else 0
                    if stagnant >= 6:   # no new venues for several scrolls → done
                        break
                raw = sorted(acc.values(), key=lambda c: c["y"])
                if raw:
                    error = None
                    break
                error = "לא נמצאו מסעדות בעמוד"
                time.sleep(2 * (attempt + 1))
        except PWTimeout as e:
            error = f"timeout: {str(e)[:80]}"
            _shot(page, "wolt_error")
        except Exception as e:
            error = str(e)[:120]
            _shot(page, "wolt_error")
        finally:
            browser.close()

    # A real Tel Aviv pizza discovery always has 100+ venues. A much smaller
    # result means Wolt served a degraded/geo-limited view (e.g. from a US CI
    # runner) — treat it like a block and DON'T overwrite the good data.
    MIN_VENUES = 40
    if len(raw) < MIN_VENUES:
        if verbose:
            print(f"  ⚠ רק {len(raw)} מסעדות נסרקו (< {MIN_VENUES}) — כנראה תצוגה חסומה/מוגבלת; "
                  f"שומר על הנתונים הקיימים ולא דורס.")
        return []

    # Cluster into visual rows by Y (tolerant), like the Pais Plus scraper.
    parsed = [_parse_card(c) for c in raw]
    ys = sorted(set(round(p["y"] / 60) * 60 for p in parsed))
    row_of = {y: i + 1 for i, y in enumerate(ys)}

    for i, p in enumerate(parsed):
        offers.append({
            "date": today, "timestamp": ts,
            "position": i + 1,
            "row": row_of[round(p["y"] / 60) * 60],
            "id": p["slug"],
            "company": p["name"] or "—",
            "offer_text": p["promo"] or p["cheapest_item"] or p["name"] or "—",
            "category": "פיצה",
            "rating": p["rating"],
            "delivery_fee": p["delivery_fee"],
            "price_text": (f'{p["price_value"]:.0f} ₪' if p["price_value"] is not None else (p["delivery_fee"] or "")),
            "price_value": p["price_value"],
            "is_preferred": p["is_preferred"],
            "product_url": p["product_url"],
        })
        if verbose and i < 8:
            print(f"  [{i+1}] row{offers[-1]['row']} {p['name']}"
                  + (f" ⭐{p['rating']}" if p['rating'] else "")
                  + (f" · {p['promo']}" if p['promo'] else ""))

    if verbose:
        print(f"\n  נמצאו {len(offers)} מסעדות פיצה בוולט")

    # Save local history (replace today's rows, keep the rest).
    history = []
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8-sig") as f:
            history = json.load(f)
    history = [h for h in history if h.get("date") != today]
    history.extend(offers)
    history.sort(key=lambda h: (h["date"], h["position"]))
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"  נשמרו → {DATA_FILE}")

    # Push to Firestore (no-op without credentials).
    try:
        import firestore_sync
        if firestore_sync.is_enabled():
            db = firestore_sync.get_client()
            db.collection("wolt_offers").document(today).set({"date": today, "offers": offers})
            print("  Synced Wolt → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    return offers


def _shot(page, name):
    try:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT_DIR / f"{name}.png"))
    except Exception:
        pass


if __name__ == "__main__":
    run_scrape()
