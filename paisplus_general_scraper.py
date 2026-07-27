"""
Pais Plus GENERAL benefits scraper (https://paisplus.co.il/) — "פייס פלוס – כללי".

Unlike paisplus_scraper.py (which scrapes the pizza-specific offers page,
/category/373), this scrapes the site's HOMEPAGE — Pais Plus's full benefits
catalog (concerts, retail discounts, movies, etc., not just pizza). Confirmed
live: only ~6 of ~314 cards on the homepage even mention "פיצה"; the user
explicitly asked for a duplicate dashboard sourced from this root URL anyway,
aware that most cards here aren't pizza offers. Company/category
classification (shared with paisplus_scraper) will label most of them
"unidentified"/"other" since they're not pizza deals — that's expected, not
a bug.

Card markup here uses `.card-item` (no `.category-page` suffix — confirmed
by inspecting the live page) but is otherwise structurally identical to the
pizza offers page, so the same field-extraction logic applies unchanged.
"""

import json, re, sys, io
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

from paisplus_scraper import identify_company, classify_category, extract_extras, safe_filename, UA

# Importing paisplus_scraper above already ran ITS stdout/stderr setup (and
# set the sentinel below) — this guard makes sure we don't wrap an
# already-wrapped stdout a second time, which would crash later with
# "I/O operation on closed file" once the orphaned first wrapper is GC'd and
# closes the shared underlying buffer out from under the second one.
if getattr(sys, "_pizza_stdio_ready", False):
    pass
elif sys.stdout is None:
    # Running under pythonw.exe (no console, e.g. from Task Scheduler) —
    # print() would crash, so write output to a log file instead.
    _log_path = Path(__file__).parent / "data" / "paisplus_general" / "scrape_log.txt"
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    _log = open(_log_path, "a", encoding="utf-8")
    sys.stdout = sys.stderr = _log
    sys._pizza_stdio_ready = True
elif sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    sys._pizza_stdio_ready = True

URL = "https://paisplus.co.il/"
CARD_SELECTOR = ".card-item"

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "paisplus_general" / "offers.json"
SHOT_DIR = ROOT / "data" / "paisplus_general" / "screenshots"


def run_scrape(verbose=True):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    shot_dir_today = SHOT_DIR / today
    shot_dir_today.mkdir(parents=True, exist_ok=True)

    offers = []
    page_screenshot_rel = None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="he-IL", viewport={"width": 1440, "height": 1000}, user_agent=UA)
        page = ctx.new_page()

        if verbose:
            print(f"[{timestamp}] פותח את {URL} ...")
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(3000)
        try:
            page.wait_for_selector(CARD_SELECTOR, timeout=15000)
        except Exception:
            pass

        # Scroll to bottom repeatedly in case of lazy-loaded cards.
        prev_count = -1
        for _ in range(15):
            count = page.locator(CARD_SELECTOR).count()
            if count == prev_count:
                break
            prev_count = count
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)

        cards = page.locator(CARD_SELECTOR)
        n = cards.count()
        if verbose:
            print(f"  נמצאו {n} קוביות הצעה")

        # Full-page screenshot, shared link for every row scraped in this run.
        page_shot_path = shot_dir_today / "full_page.png"
        page.screenshot(path=str(page_shot_path), full_page=True)
        page_screenshot_rel = str(page_shot_path.relative_to(ROOT)).replace("\\", "/")

        raw_cards = []
        for i in range(n):
            el = cards.nth(i)
            try:
                data = el.evaluate("""el => {
                    const rect = el.getBoundingClientRect();
                    const img = el.querySelector('.card-img');
                    const title = el.querySelector('.card-title');
                    const sub = el.querySelector('.card-sub-title');
                    const priceText = el.querySelector('.price-text');
                    const priceNum = el.querySelector('.price-number');
                    return {
                        top: rect.top + window.scrollY,
                        left: rect.left + window.scrollX,
                        dataId: el.getAttribute('data-id'),
                        href: el.getAttribute('href'),
                        cls: el.getAttribute('class'),
                        img: img ? img.getAttribute('src') : null,
                        alt: img ? img.getAttribute('alt') : null,
                        title: title ? title.innerText.trim() : '',
                        subtitle: sub ? sub.innerText.trim() : '',
                        priceText: priceText ? priceText.innerText.trim() : '',
                        priceNum: priceNum ? priceNum.innerText.trim() : '',
                        fullText: (el.innerText || '').replace(/\\s+/g, ' ').trim(),
                    };
                }""")
                raw_cards.append(data)
            except Exception as e:
                if verbose:
                    print(f"  [warn] card {i} read failed: {e}")
                continue

        # Cluster into visual rows by absolute Y position (tolerant of a few px jitter).
        rows_sorted = sorted(set(round(c["top"] / 20) * 20 for c in raw_cards))
        row_index = {y: idx + 1 for idx, y in enumerate(rows_sorted)}

        for i, c in enumerate(raw_cards):
            data_id = c["dataId"] or f"idx{i}"
            is_preferred = "favored" in (c["cls"] or "")
            company, match_method = identify_company(
                c["title"] + " " + c["subtitle"] + " " + (c["alt"] or ""), data_id)
            category = classify_category(c["title"] + " " + c["subtitle"])
            extras = extract_extras(c["title"])
            price_value = None
            pm = re.search(r"[\d.]+", c["priceNum"] or "")
            if pm:
                try:
                    price_value = float(pm.group())
                except ValueError:
                    pass

            cube_shot_name = f"card_{safe_filename(data_id)}.png"
            cube_shot_path = shot_dir_today / cube_shot_name
            try:
                el = cards.nth(i)
                el.scroll_into_view_if_needed(timeout=5000)
                el.screenshot(path=str(cube_shot_path))
                cube_screenshot_rel = str(cube_shot_path.relative_to(ROOT)).replace("\\", "/")
            except Exception as e:
                if verbose:
                    print(f"  [warn] screenshot failed for card {data_id}: {e}")
                cube_screenshot_rel = None

            offers.append({
                "date": today,
                "timestamp": timestamp,
                "position": i + 1,
                "row": row_index.get(round(c["top"] / 20) * 20),
                "id": data_id,
                "company": company,
                "company_match_method": match_method,
                "offer_text": c["title"],
                "category": category,
                "extras": extras,
                "price_text": f"{c['priceText']} {c['priceNum']}".strip(),
                "price_value": price_value,
                "is_preferred": is_preferred,
                "additional_info": c["subtitle"],
                "full_text": c["fullText"],
                "cube_screenshot": cube_screenshot_rel,
                "page_screenshot": page_screenshot_rel,
                "product_url": ("https://paisplus.co.il" + c["href"]) if c["href"] else None,
            })

            if verbose:
                pref = " ⭐מועדפת" if is_preferred else ""
                print(f"  [{i+1}/{n}] {company}: {c['title'][:50]}{pref}")

        browser.close()

    # Guard: never let an empty scrape (e.g. blocked by queue-it on CI, or a
    # network hiccup) wipe out good data that's already saved and live.
    if not offers:
        if verbose:
            print("\n  ⚠ 0 הצעות נסרקו — שומר על הנתונים הקיימים ולא דורס. "
                  "(ייתכן שהאתר חסם את הגישה)")
        return offers

    # Save — replace any prior entries for today, then append the fresh batch.
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8-sig") as f:
            history = json.load(f)
    history = [h for h in history if h.get("date") != today]
    history.extend(offers)
    history.sort(key=lambda h: (h["date"], h["position"]))
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"\n  נשמרו {len(offers)} הצעות → {DATA_FILE}")

    # Push to Firestore (no-op if credentials aren't configured)
    try:
        import firestore_sync
        firestore_sync.push_paisplus_general_offers(offers, date=today)
        firestore_sync.mark_site_status(
            "paisplus_general", ok=True,
            timestamp=offers[0].get("timestamp") if offers else today)
        if verbose and firestore_sync.is_enabled():
            print("  Synced Pais Plus (general) → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    if verbose:
        print("Done.")

    return offers


if __name__ == "__main__":
    run_scrape()
