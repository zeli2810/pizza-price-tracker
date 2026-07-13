"""
Pais Plus pizza-deals scraper (https://paisplus.co.il/category/373)

Scrapes every offer "card" on the page and records, per card: the pizza
chain, the offer text, an auto-classified category (one pizza / two pizzas /
etc.), the price, whether it's marked "favored" (מועדפת), a per-card
screenshot, and a link to a full-page screenshot.

Company/category are inferred from the card's own text (there's no public
API exposing a clean taxonomy), so ambiguous cards fall back to
"לא זוהה מהטקסט" — check the card screenshot's logo in that case.
"""

import json, re, sys, io
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

if sys.stdout is None:
    # Running under pythonw.exe (no console, e.g. from Task Scheduler) —
    # print() would crash, so write output to a log file instead.
    _log_path = Path(__file__).parent / "data" / "paisplus" / "scrape_log.txt"
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    _log = open(_log_path, "a", encoding="utf-8")
    sys.stdout = sys.stderr = _log
elif sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

URL = "https://paisplus.co.il/category/373"

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "paisplus" / "offers.json"
SHOT_DIR = ROOT / "data" / "paisplus" / "screenshots"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# ── company identification (by card text) ──────────────────────────────────
COMPANY_KEYWORDS = [
    ("דומינו",        "דומינו'ס"),
    ("פיצה האט",      "פיצה האט"),
    ("פאפא ג'ונס",    "פאפא ג'ונס"),
    ("פאפא'ג",        "פאפא ג'ונס"),
    ("פיצה פרגו",      "פיצה פרגו"),
    ("פיצה שמש",      "פיצה שמש"),
    ("פיצה סטורי",     "פיצה סטורי"),
    ("ביג אפל פיצה",   "ביג אפל פיצה"),
    ("ביג אפל",        "ביג אפל פיצה"),
]
UNKNOWN_COMPANY = "לא זוהה מהטקסט (בדקו את הלוגו בצילום)"

# Many cards show the chain only as a logo image, not in the text — these
# specific recurring product IDs were confirmed once by eye from their cube
# screenshot. Add more entries here as new unidentified IDs get confirmed.
ID_OVERRIDES = {
    "33617": "פאפא ג'ונס",
    "22161": "דומינו'ס",
    "22240": "דומינו'ס",
    "22241": "דומינו'ס",
    "22242": "דומינו'ס",
    "22250": "דומינו'ס",
    "22252": "דומינו'ס",
    "23699": "דומינו'ס",
    "22556": "פיצה האט",
}

# Chain names that themselves contain the word "פיצה" — stripped out before
# scanning for pizza-count keywords so the company name isn't mistaken for
# an actual pizza mentioned in the offer.
BRAND_PHRASES_WITH_PIZZA_WORD = ["פיצה פרגו", "פיצה האט", "פיצה שמש", "פיצה סטורי"]

HEBREW_NUMBERS = {
    "שני": 2, "שתי": 2, "שלוש": 3, "שלושה": 3, "ארבע": 4, "ארבעה": 4,
    "חמש": 5, "חמישה": 5, "שש": 6, "שישה": 6, "שבע": 7, "שבעה": 7,
    "שמונה": 8, "תשע": 9, "תשעה": 9, "עשר": 10, "עשרה": 10,
}
COUNT_RE = re.compile(
    r'(\d+|' + "|".join(HEBREW_NUMBERS) + r')\s*(פיצות|משפחתיות|משפחתיים|מגשים)'
)
PIZZA_WORD_RE = re.compile(r'(פיצות|פיצה|משפחתיות|משפחתיים|משפחתית|משפחתי|מגשים|מגש)')
PLURAL_NO_COUNT_RE = re.compile(r'(פיצות|משפחתיות|משפחתיים|מגשים)')


def identify_company(text, product_id=None):
    if product_id in ID_OVERRIDES:
        return ID_OVERRIDES[product_id], "לוגו (מזהה ידוע)"
    for kw, name in COMPANY_KEYWORDS:
        if kw in text:
            return name, "טקסט"
    return UNKNOWN_COMPANY, "לא זוהה"


def classify_category(text):
    stripped = text
    for phrase in BRAND_PHRASES_WITH_PIZZA_WORD:
        stripped = stripped.replace(phrase, " ")

    counts = []
    for m in COUNT_RE.finditer(stripped):
        raw = m.group(1)
        counts.append(int(raw) if raw.isdigit() else HEBREW_NUMBERS[raw])
    if counts:
        n = max(counts)
        if n == 1:
            return "פיצה אחת"
        if n == 2:
            return "שתי פיצות"
        return f"{n} פיצות"

    if not PIZZA_WORD_RE.search(stripped):
        return "אחר / לא כולל פיצה מפורשת"

    if PLURAL_NO_COUNT_RE.search(stripped):
        return "מספר פיצות (כמות לא צוינה)"

    return "פיצה אחת"


def extract_extras(title):
    """Everything after the first '+' in the title = what's included besides the pizza(s)."""
    parts = title.split("+")
    if len(parts) <= 1:
        return ""
    extras = [p.strip() for p in parts[1:]]
    # Drop a trailing " - <company>" tail from the last extra segment, if present.
    if extras:
        last = extras[-1]
        m = re.split(r"\s-\s", last)
        if len(m) > 1:
            for kw, _ in COMPANY_KEYWORDS:
                if kw in m[-1]:
                    last = m[0].strip()
                    break
        extras[-1] = last
    return " | ".join(e for e in extras if e)


def safe_filename(s):
    return re.sub(r"[^\w\-]+", "_", s)[:120]


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
            page.wait_for_selector(".card-item.category-page", timeout=15000)
        except Exception:
            pass

        # Scroll to bottom repeatedly in case of lazy-loaded cards.
        prev_count = -1
        for _ in range(15):
            count = page.locator(".card-item.category-page").count()
            if count == prev_count:
                break
            prev_count = count
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)

        cards = page.locator(".card-item.category-page")
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
        firestore_sync.push_paisplus_offers(offers, date=today)
        firestore_sync.mark_site_status(
            "paisplus", ok=True,
            timestamp=offers[0].get("timestamp") if offers else today)
        if verbose and firestore_sync.is_enabled():
            print("  Synced Pais Plus → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    if verbose:
        print("Done.")

    return offers


if __name__ == "__main__":
    run_scrape()
