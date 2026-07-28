"""
Wolt competitor-presence scraper — Papa John's / Pizza Hut, by Wolt delivery area.

Wolt does NOT resolve location per municipality — it groups all of Israel into
a fixed set of ~19-24 named delivery "areas" (discovered via its own sitemap:
https://wolt.com/sitemap/cities/isr-1.xml), each bundling several nearby cities
(e.g. one "hasharon" area covers Netanya/Kfar Saba/Ra'anana/Herzliya together).
Two things were verified by hand before writing this:

  1. The area is resolved from the URL PATH SLUG of a search page
     (wolt.com/he/isr/<area-slug>/search?q=...), NOT from browser geolocation —
     a Playwright geolocation override has NO effect on these results.
  2. An INVALID/guessed slug does not error — it silently falls back to a
     generic Tel-Aviv-area default. So this script only ever navigates to the
     hardcoded, sitemap-verified AREA slugs below — never a guessed city slug.

Each population->40k+ city is labeled under its real containing Wolt area (see
AREAS). A few smaller cities (see UNCOVERED_CITIES) couldn't be confidently
mapped to any of Wolt's areas and are reported as "not checked" rather than
guessed, per the project owner's explicit choice.

Output: data/wolt_competitors.json (latest snapshot) + Firestore
wolt_competitors/latest ({checked_at, areas:[{slug,label,cities,papa_johns,
pizza_hut,status}], uncovered_cities:[...]}).
"""

import json
import re
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from multi_scraper import UA  # also sets UTF-8 stdout on Windows

DATA_FILE = Path(__file__).parent / "data" / "wolt_competitors.json"

SEARCH_URL_TMPL = "https://wolt.com/he/isr/{slug}/search?q={q}"
QUERIES = {"papa_johns": "פאפא ג'ונס", "pizza_hut": "פיצה האט"}

BLOCK_MARKERS = ["just a moment", "cloudflare", "attention required", "verifying you are human"]

# Wolt delivery areas (sitemap-verified slugs) that cover at least one Israeli
# city with population above ~40,000. label/cities are for DISPLAY only — the
# slug is the only thing that actually drives the search.
AREAS = [
    ("tel-aviv", "תל אביב וגוש דן",
     ["תל אביב-יפו", "רמת גן", "בני ברק", "חולון", "בת ים", "גבעתיים", "קריית אונו", "אור יהודה"]),
    ("herzliya", "הרצליה", ["הרצליה"]),
    ("hasharon", "השרון", ["נתניה", "כפר סבא", "רעננה", "הוד השרון", "רמת השרון"]),
    ("petah-tikva", "פתח תקווה והסביבה", ["פתח תקווה", "ראש העין", "לוד", "רמלה", "אלעד"]),
    ("beer-sheva", "באר שבע והנגב", ["באר שבע", "דימונה"]),
    ("ashkelon", "אשקלון", ["אשקלון"]),
    ("jerusalem", "ירושלים", ["ירושלים", "ביתר עילית"]),
    ("haifa", "חיפה והקריות", ["חיפה", "קריית אתא", "קריית ביאליק", "קריית מוצקין"]),
    ("modiin", "מודיעין והסביבה", ["מודיעין-מכבים-רעות", "מודיעין עילית"]),
    ("eilat", "אילת", ["אילת"]),
    ("rishon-lezion-hashfela-area", "ראשון לציון והשפלה", ["ראשון לציון", "רחובות", "יבנה"]),
    ("ashdod-and-lachish-area", "אשדוד ולכיש", ["אשדוד", "קריית גת"]),
    ("acre-nahariya-area", "עכו-נהריה", ["עכו", "נהריה", "שפרעם"]),
    ("beit-shemesh-area", "בית שמש", ["בית שמש"]),
    ("tiberias-area", "טבריה", ["טבריה"]),
    ("karmiel-area", "כרמיאל", ["כרמיאל"]),
    ("afula-emek-yizrael-area", "עפולה ועמק יזרעאל", ["עפולה"]),
    ("nazareth---nof-hagalil-area", "נצרת ונוף הגליל", ["נצרת", "נוף הגליל"]),
    ("netivot-sderot-area", "נתיבות-שדרות", ["נתיבות", "אופקים"]),
    ("pardes-hanna", "פרדס חנה וחדרה", ["פרדס חנה-כרכור", "חדרה"]),
]

# Cities (population > 40k) that couldn't be confidently mapped to one of
# Wolt's delivery areas above — reported as unchecked rather than guessed.
UNCOVERED_CITIES = ["רהט", "אום אל-פחם", "טייבה"]

PAPA_JOHNS_MARKERS = ["פאפאגונס", "papajohn"]
PIZZA_HUT_MARKERS = ["פיצההאט", "pizzahut"]

_EXTRACT_JS = r"""
() => {
  const seen = new Set();
  const out = [];
  document.querySelectorAll('a[href*="/restaurant/"]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (seen.has(href)) return;
    seen.add(href);
    // Cards often carry a KOSHER badge / promo banner as leading text before
    // the venue name, so scan the WHOLE card text — not just the first line.
    const card = a.closest('[data-test-id]') || a;
    out.push((card.innerText || '').replace(/\s+/g, ' ').trim());
  });
  return out;
}
"""


def _norm(s):
    s = (s or "").lower()
    s = re.sub(r"[’'`׳]", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def _chain_present(names, markers):
    return any(any(m in _norm(n) for m in markers) for n in names)


def _search_names(page, slug, query, verbose):
    url = SEARCH_URL_TMPL.format(slug=slug, q=quote(query))
    for attempt in range(3):
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
        except Exception:
            time.sleep(2)
            continue
        page.wait_for_timeout(4500 + attempt * 1500)
        body = (page.inner_text("body") or "").lower()
        if any(m in body for m in BLOCK_MARKERS):
            time.sleep(2 * (attempt + 1))
            continue
        names = page.evaluate(_EXTRACT_JS)
        if names:
            return names, None
        time.sleep(1.5 * (attempt + 1))
    return [], "no_results"


def check_area(browser, slug, label, cities, verbose=True):
    ctx = browser.new_context(
        locale="he-IL", timezone_id="Asia/Jerusalem", viewport={"width": 1280, "height": 900}, user_agent=UA)
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
    page = ctx.new_page()
    result = {"slug": slug, "label": label, "cities": cities,
              "papa_johns": False, "pizza_hut": False, "status": "ok"}
    try:
        pj_names, pj_err = _search_names(page, slug, QUERIES["papa_johns"], verbose)
        ph_names, ph_err = _search_names(page, slug, QUERIES["pizza_hut"], verbose)
        if pj_err and ph_err:
            result["status"] = "blocked"
        else:
            result["papa_johns"] = _chain_present(pj_names, PAPA_JOHNS_MARKERS)
            result["pizza_hut"] = _chain_present(ph_names, PIZZA_HUT_MARKERS)
    except PWTimeout:
        result["status"] = "timeout"
    except Exception as e:
        result["status"] = f"error: {str(e)[:80]}"
    finally:
        ctx.close()
    if verbose:
        pj_mark = "✓" if result["papa_johns"] else ("?" if result["status"] != "ok" else "—")
        ph_mark = "✓" if result["pizza_hut"] else ("?" if result["status"] != "ok" else "—")
        print(f"  {label}: פאפא ג'ונס {pj_mark} · פיצה האט {ph_mark}"
              + (f" [{result['status']}]" if result["status"] != "ok" else ""))
    return result


def run_scrape(verbose=True):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    if verbose:
        print(f"  Wolt competitor scan — {len(AREAS)} delivery areas (Papa John's / Pizza Hut)...")

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome", headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        try:
            for slug, label, cities in AREAS:
                results.append(check_area(browser, slug, label, cities, verbose=verbose))
        finally:
            browser.close()

    ok = [r for r in results if r["status"] == "ok"]
    if verbose:
        print(f"\n  {len(ok)}/{len(results)} אזורים נסרקו בהצלחה; "
              f"פאפא ג'ונס ב-{sum(1 for r in ok if r['papa_johns'])} אזורים, "
              f"פיצה האט ב-{sum(1 for r in ok if r['pizza_hut'])} אזורים.")

    # A near-total failure means Wolt served a degraded view (e.g. from a
    # non-Israeli IP) — treat it like a block and DON'T overwrite good data.
    MIN_OK = max(3, len(AREAS) // 3)
    if len(ok) < MIN_OK:
        if verbose:
            print(f"  ⚠ רק {len(ok)} אזורים הצליחו (< {MIN_OK}) — כנראה חסימה/IP לא ישראלי; "
                  f"שומר על הנתונים הקיימים ולא דורס.")
        return []

    entry = {"checked_at": ts, "areas": results, "uncovered_cities": UNCOVERED_CITIES}
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"  נשמרו → {DATA_FILE}")

    try:
        import firestore_sync
        if firestore_sync.is_enabled():
            db = firestore_sync.get_client()
            db.collection("wolt_competitors").document("latest").set(entry)
            if verbose:
                print("  Synced Wolt competitors → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    return results


if __name__ == "__main__":
    run_scrape()
