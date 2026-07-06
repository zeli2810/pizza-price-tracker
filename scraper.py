"""
Pizza Price Tracker - Israel
Scrapes family pizza prices from Domino's, Pizza Hut, and Papa John's Israel.
Run daily at 14:00 via Windows Task Scheduler.
"""

import json
import re
import sys
import io
import requests
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DATA_FILE = Path(__file__).parent / "data" / "prices.json"

SOURCES = {
    "dominos":   {"name": "דומינוס פיצה", "color": "#0078AE"},
    "pizzahut":  {"name": "פיצה האט",     "color": "#E31837"},
    "papajohns": {"name": "פאפא ג'ונס",   "color": "#006341"},
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def extract_price(text):
    if not text:
        return None
    text = text.replace(",", "").replace("\xa0", " ").replace("‏", "")
    for m in re.findall(r"[\d]+(?:[.]\d{1,2})?", text):
        val = float(m)
        if 20 < val < 500:
            return val
    return None


def find_in_texts(texts):
    """Scan text nodes for family, single-meal, double-meal prices."""
    family_kw = ["משפחתית", "family", "גדולה", "XL", "לארג", "L פיצה", "פיצה גד", "14\""]
    single_kw = ["ארוחה", "מנה", "ל-1", "ליחיד", "1 פיצה", "סט ל-1"]
    double_kw = ["זוגית", "ל-2", "שתי פיצות", "2 פיצות", "לשניים", "סט ל-2", "ב-2"]
    out = {"family": None, "meal_single": None, "meal_double": None}
    for txt in texts:
        price = extract_price(txt)
        if not price:
            continue
        if out["family"] is None and any(k in txt for k in family_kw):
            out["family"] = price
        if out["meal_single"] is None and any(k in txt for k in single_kw):
            out["meal_single"] = price
        if out["meal_double"] is None and any(k in txt for k in double_kw):
            out["meal_double"] = price
    return out


def walk_json_for_family_pizza(obj, path=""):
    """
    Walk a JSON tree looking for price fields near 'family' or 'משפחתית' context.
    Returns list of (path, price, context) tuples.
    """
    results = []
    FAMILY_KW = ["משפחתית", "family", "large", "xl", "14\""]
    PRICE_KW   = ["price", "Price", "מחיר"]

    def walk(node, p):
        if isinstance(node, dict):
            name_field = str(node.get("name", "") or node.get("Name", "") or node.get("title", "")).lower()
            is_family = any(k in name_field for k in FAMILY_KW)
            for k, v in node.items():
                if k in PRICE_KW and is_family:
                    try:
                        val = float(v)
                        if 20 < val < 500:
                            results.append((f"{p}.{k}", val, name_field))
                    except Exception:
                        pass
                walk(v, f"{p}.{k}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{p}[{i}]")

    walk(obj, path)
    return results


# ── Domino's (API-based) ──────────────────────────────────────────────────────

def scrape_dominos():
    """
    Domino's Israel API flow:
    1. POST /connect (get JWT token)
    2. POST /getStoreList (find open stores)
    3. POST /selectSubService (pickup)
    4. POST /selectPickupStore (first open store)
    5. POST /getMenu (full menu with prices)
    """
    r = {"family": None, "meal_single": None, "meal_double": None, "note": None}

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.dominos.co.il",
        "Referer": "https://www.dominos.co.il/",
        "Accept-Language": "he-IL,he;q=0.9",
    })
    req_num = [1]

    def call(ep, payload=None):
        if payload is None:
            payload = {}
        payload["requestNum"] = req_num[0]
        req_num[0] += 1
        resp = sess.post(f"https://api.dominos.co.il/{ep}", json=payload, timeout=15)
        return resp.json()

    try:
        # Connect
        data = call("connect", {
            "lang": "he", "hardware": "PC", "runtime": "browser",
            "appVersion": "1.16.3", "browserType": "Chrome", "os": "Windows",
            "deviceModel": "", "referrer": "", "url": "https://www.dominos.co.il/"
        })
        token = data.get("data", {}).get("accessToken", "")
        if not token:
            r["error"] = "connect failed"
            return r
        sess.headers["token"] = token

        call("setLang", {"lang": "he"})

        # Get store list
        stores_data = call("getStoreList")
        stores = stores_data.get("data", [])
        open_stores = [s for s in stores if s.get("isOpen")]

        if not open_stores:
            r["note"] = f"כל הסניפים סגורים כעת ({len(stores)} סניפים). מחירים ממועד הסריקה הקודם."
            return r

        # selectSubService
        call("selectSubService", {"subService": "pu"})

        # Try open stores until one works
        menu_data = None
        for store in open_stores[:5]:
            sid = str(store["id"])
            sel = call("selectPickupStore", {"storeId": sid})
            if sel.get("status") == "success":
                # Get the menu
                menu_resp = call("getMenu", {})
                if menu_resp.get("status") == "success":
                    menu_data = menu_resp.get("data", {})
                    break

        if not menu_data:
            r["note"] = "לא ניתן היה לטעון תפריט"
            return r

        # Walk menu for family pizza prices
        found = walk_json_for_family_pizza(menu_data)
        if found:
            r["family"] = found[0][1]

        # Also look for deal/meal prices
        menu_str = json.dumps(menu_data, ensure_ascii=False)
        texts = [t for t in re.findall(r'[^\n{}\[\]]{5,150}', menu_str) if re.search(r'\d', t)]
        prices = find_in_texts(texts)
        r["meal_single"]  = r.get("meal_single") or prices.get("meal_single")
        r["meal_double"]  = r.get("meal_double") or prices.get("meal_double")

    except Exception as e:
        r["error"] = str(e)[:100]

    return r


# ── Pizza Hut (Playwright) ────────────────────────────────────────────────────

def scrape_pizzahut(page):
    """
    Pizza Hut Israel - homepage shows promotional deals with prices.
    Also tries to navigate to the ordering page for more prices.
    """
    r = {"family": None, "meal_single": None, "meal_double": None, "raw": []}
    try:
        page.goto("https://www.pizzahut.co.il", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        # Accept Cookiebot
        for sel in ["#CybotCookiebotDialogBodyButtonAccept",
                    "a#CybotCookiebotDialogBodyButtonAccept",
                    "button:has-text('הסכמה')"]:
            try:
                page.click(sel, timeout=3000)
                page.wait_for_timeout(1000)
                break
            except Exception:
                pass

        page.wait_for_timeout(1500)

        def extract_price_segments():
            """Get all short text segments that contain a price (₪ or numeric near price words)."""
            return page.evaluate("""() => {
                // Get body visible text and split into segments
                const body = document.body ? (document.body.innerText || '') : '';
                // Split by newlines and filter for segments with numbers
                const lines = body.split(/[\\n\\r]+/).map(l => l.trim()).filter(l => l.length > 2 && l.length < 300 && /[0-9]/.test(l));
                // Also grab from individual nodes with ₪
                const seen = new Set(lines);
                const extra = [];
                document.querySelectorAll('*').forEach(el => {
                    const t = (el.innerText || '').trim();
                    if (t && t.length < 300 && !seen.has(t) && t.includes('\\u20aa')) {
                        seen.add(t); extra.push(t);
                    }
                });
                return [...lines, ...extra].slice(0, 100);
            }""")

        texts_home = extract_price_segments()
        prices_home = find_in_texts(texts_home)

        # Try to navigate to ordering pages that may show menu prices
        for url in ["https://www.pizzahut.co.il/order", "https://order.pizzahut.co.il"]:
            try:
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                if page.url != "https://www.pizzahut.co.il/":
                    break
            except Exception:
                pass

        texts_menu = extract_price_segments()
        all_texts = list(dict.fromkeys(texts_home + texts_menu))
        r["raw"] = all_texts[:15]

        prices_menu = find_in_texts(texts_menu)
        for k in ("family", "meal_single", "meal_double"):
            r[k] = prices_menu[k] or prices_home[k]

    except Exception as e:
        r["error"] = str(e)[:100]
    return r


# ── Papa John's (Playwright + stealth headers) ────────────────────────────────

def scrape_papajohns(page):
    """
    Papa John's Israel — protected by Akamai.
    Tries multiple URL variants and an alternative ordering platform.
    """
    r = {"family": None, "meal_single": None, "meal_double": None, "raw": []}

    candidate_urls = [
        "https://www.papajohns.co.il",
        "https://papajohns.co.il",
        "https://www.papajohns.co.il/menu",
    ]

    loaded = False
    for url in candidate_urls:
        try:
            resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            title = page.title()
            if resp and resp.status < 400 and "Access Denied" not in title:
                loaded = True
                break
        except Exception:
            continue

    if not loaded:
        r["error"] = "האתר חסום על ידי Akamai CDN"
        return r

    # Dismiss popups
    for sel in ["button:has-text('סגור')", "button:has-text('אישור')", ".close", ".modal-close"]:
        try:
            page.click(sel, timeout=1500)
            page.wait_for_timeout(500)
        except Exception:
            pass

    # Navigate to menu
    for sel in ["a:has-text('תפריט')", "a:has-text('פיצות')", "a[href*='menu']"]:
        try:
            page.click(sel, timeout=2000)
            page.wait_for_timeout(1500)
            break
        except Exception:
            pass

    texts = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText || '').trim();
            if (t && t.length < 300 && !seen.has(t) && t.includes('₪')) {
                seen.add(t); out.push(t);
            }
        });
        return out.slice(0, 40);
    }""")

    r["raw"] = texts[:15]
    prices = find_in_texts(texts)
    r.update(prices)
    return r


# ── Main ──────────────────────────────────────────────────────────────────────

def run_scrape(verbose=True):
    if verbose:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting pizza price scrape...")

    today     = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scraped   = {"date": today, "timestamp": timestamp, "sources": {}}

    # ── Domino's (API, no browser needed) ──
    name_dom = SOURCES["dominos"]["name"]
    if verbose:
        print(f"  Scraping {name_dom} (API)...")
    dom_result = scrape_dominos()
    scraped["sources"]["dominos"] = {
        "name":        name_dom,
        "family":      dom_result.get("family"),
        "meal_single": dom_result.get("meal_single"),
        "meal_double": dom_result.get("meal_double"),
        "error":       dom_result.get("error"),
        "note":        dom_result.get("note"),
        "raw_samples": [],
    }
    if verbose:
        f = dom_result.get("family"); s = dom_result.get("meal_single"); d = dom_result.get("meal_double")
        note = dom_result.get("note", "")
        print(f"    {name_dom}: family={f} single={s} double={d}" + (f" | {note[:50]}" if note else ""))

    # ── Pizza Hut + Papa John's (Playwright) ──
    pl_scrapers = {
        "pizzahut":  scrape_pizzahut,
        "papajohns": scrape_papajohns,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="he-IL",
            viewport={"width": 1280, "height": 900},
            user_agent=UA,
            extra_http_headers={"Accept-Language": "he-IL,he;q=0.9"},
        )

        for key, fn in pl_scrapers.items():
            name = SOURCES[key]["name"]
            if verbose:
                print(f"  Scraping {name}...")
            page = ctx.new_page()
            try:
                result = fn(page)
            except Exception as e:
                result = {"family": None, "meal_single": None, "meal_double": None, "error": str(e)[:100]}
            finally:
                page.close()

            scraped["sources"][key] = {
                "name":        name,
                "family":      result.get("family"),
                "meal_single": result.get("meal_single"),
                "meal_double": result.get("meal_double"),
                "error":       result.get("error"),
                "raw_samples": result.get("raw", [])[:8],
            }

            if verbose:
                f  = result.get("family")
                s  = result.get("meal_single")
                d  = result.get("meal_double")
                ok = "[OK]" if (f or s or d) else "[no prices]"
                err = f" | {result['error'][:60]}" if result.get("error") else ""
                print(f"    {name}: family={f} single={s} double={d} {ok}{err}")

        browser.close()

    # Save — replace today's entry
    history = load_history()
    history = [h for h in history if h["date"] != today]
    history.append(scraped)
    history.sort(key=lambda x: x["date"])
    save_history(history)

    if verbose:
        print(f"  Saved -> {DATA_FILE}")
        print("Done.")

    return scraped


if __name__ == "__main__":
    run_scrape()
