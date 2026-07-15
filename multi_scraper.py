"""
Multi-chain Pizza Price Tracker (Israel)
Scrapes 3 price points from 3 pizza chains daily at 14:00, all referenced to a
fixed Tel Aviv address/branch (דיזנגוף 50 / יגאל אלון 90 / Dizengoff-area branch):
  - family      : price of the cheapest family/large pizza from the pizza menu
  - meal_single : price of the cheapest single-pizza meal deal
  - meal_double : price of the cheapest two-pizza meal deal

Chains:
  dominos   -> api.dominos.co.il  (REST API, no browser)
  pizzahut  -> order.pizzahut.co.il/27/menu  (Atmos SPA, Playwright + route intercept; store 27 = Tel Aviv/Dizengoff)
  papajohns -> papajohns.co.il/shop/  (WooCommerce, Playwright + stealth)
"""

import json, re, sys, io, time, os
import requests
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DATA_FILE = Path(__file__).parent / "data" / "all_prices.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

TLV_ADDRESS = "דיזנגוף 50 תל אביב"
TLV_CITY = "תל אביב"

CHAINS = {
    "dominos":   {"name": "דומינוס",      "color": "#0078AE"},
    "pizzahut":  {"name": "פיצה האט",     "color": "#E31837"},
    "papajohns": {"name": "פאפא ג'ונס",   "color": "#006341"},
}

# ── helpers ────────────────────────────────────────────────────────────────────

def _empty_prices():
    return {"family": None, "meal_single": None, "meal_double": None}

def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    return []

def save_history(history):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def pick_price(text):
    """Extract first reasonable price from text."""
    if not text:
        return None
    text = str(text).replace(",", "").replace("\xa0", " ")
    for m in re.findall(r"[\d]+(?:[.]\d{1,2})?", text):
        v = float(m)
        if 20 < v < 800:
            return v
    return None

FAMILY_KW    = ["משפחתית", "משפחתי", "family", "large", "xl", 'l פיצה', "14\"", "לארג"]
SINGLE_KW    = ["ארוחה", "סט ל-1", "ל-1", "single", "1 פיצה", "פיצה אחת", "ארוחת 1"]
DOUBLE_KW    = ["זוגי", "ל-2", "שתי פיצות", "2 פיצות", "double", "ארוחת 2", "לשניים", "צמד",
                "2 משפחתי", "2 משפחתיות"]
MEAL_KW      = ["ארוחה", "ארוחות", "deal", "מבצע", "combo", "meal", "חבילה"]
# Patterns that indicate a single-pizza meal deal (pizza + extras)
SINGLE_MEAL_KW = ["משפחתית + ", "משפחתי + ", "+ נלווה", "+ קינוח", "+ שתיה", "+ שתייה", "+ פחית"]
PIZZA_CAT_KW = ["פיצ", "pizza"]
# A pizza *meal* must actually contain a pizza. Family/large keywords count too,
# because at these chains "משפחתית" always refers to a pizza size.
PIZZA_REF_KW = ["פיצ", "pizza", "משפחתי", "משפחתית", "מגש", 'l ', "xl", "14\""]
# Non-pizza mains that must never be counted as a pizza meal (a "+ drink" combo
# built around a sandwich/chicken would otherwise win the cheapest-price pick).
NON_PIZZA_KW = ["כריך", "סנדוויץ", "צ'יקן", "chicken", "נאגט", "טורטיה",
                "סלט", "salad", "wrap", "wings", "כנפי", "מוצרלה סטיקס", "פוקצ"]

def kw_match(text, kws):
    t = text.lower()
    return any(k.lower() in t for k in kws)

def is_pizza_item(ctx):
    """True only if the context references a pizza and isn't a non-pizza main."""
    return kw_match(ctx, PIZZA_REF_KW) and not kw_match(ctx, NON_PIZZA_KW)

def is_multi_pizza(ctx):
    """Return True if context clearly refers to more than one pizza."""
    import re as _re
    return bool(_re.search(r'\b[2-9]\s+(?:פיצות|משפחתי)', ctx))

def walk_json_prices(obj, out=None, ctx=""):
    """Walk JSON tree collecting (price, context) tuples."""
    if out is None:
        out = []
    PRICE_KEYS = {"price", "Price", "basePrice", "unitPrice", "defaultPrice", "מחיר"}
    if isinstance(obj, dict):
        name = str(obj.get("name") or obj.get("Name") or obj.get("title") or obj.get("categoryName") or "")
        ctx2 = (ctx + " | " + name).strip(" |")
        for k, v in obj.items():
            if k in PRICE_KEYS:
                p = pick_price(v)
                if p:
                    out.append((p, ctx2))
            else:
                walk_json_prices(v, out, ctx2)
    elif isinstance(obj, list):
        for item in obj:
            walk_json_prices(item, out, ctx)
    return out

def classify_prices(pairs):
    """Given list of (price, ctx) pairs, return {family, meal_single, meal_double}."""
    families, singles, doubles = [], [], []
    for price, ctx in pairs:
        c = ctx.lower()
        # Every bucket requires the item to actually be a pizza (not a
        # sandwich/chicken combo that happens to be cheaper).
        if not is_pizza_item(ctx):
            continue
        if kw_match(c, DOUBLE_KW) or is_multi_pizza(ctx):
            doubles.append(price)
        elif kw_match(ctx, SINGLE_MEAL_KW):
            singles.append(price)
        elif kw_match(c, SINGLE_KW) and kw_match(c, MEAL_KW):
            singles.append(price)
        elif kw_match(c, FAMILY_KW):
            families.append(price)

    def pick(lst):
        # Cheapest/most basic matching item — consistent "apples to apples" comparison.
        return min(lst) if lst else None

    return {"family": pick(families), "meal_single": pick(singles), "meal_double": pick(doubles)}


# ── Pizza Hut: structure-aware classifier ──────────────────────────────────────
# Pizza Hut's menu is a "promo swamp": the SAME product is listed at many
# simultaneous prices (retailer deals, app deals, holiday deals…). A plain
# cheapest-match would grab a random promo. Per the product decision we track
# the STANDARD price, identified via category structure + clean item names.
# Best-effort: if Pizza Hut restructures its menu this may need re-tuning.
PH_RETAILER_PROMO = ["שופרסל", "וולט", "סופר פארם", "בנק", "haat", "סיבוס", "עכו",
                     "טיקטוק", "ווצאפ", "sms", "נופשונית", "פסח", "מבצע", "סליידר",
                     "הטבת", "finest", "tiktok", "ta ", "שופר"]

def _ph_is_promo(name):
    low = name.lower()
    return any(p in low for p in PH_RETAILER_PROMO)

def _ph_has_embedded_price(name):
    # A 2-3 digit number inside a MEAL name is a baked-in promo price (pizza
    # *sizes* like 14"/16" only appear in single-pizza names, not meal names).
    return bool(re.search(r"\d{2,3}", name))

def _ph_name(x):
    n = x.get("name") or ""
    return (n.get("he") if isinstance(n, dict) else n) or ""

def classify_pizzahut(menu):
    """Classify a Pizza Hut getMenu payload into family/meal_single/meal_double."""
    if not isinstance(menu, dict):
        return _empty_prices()
    items = {it.get("id"): it for it in menu.get("items", []) if it.get("active", True)}
    cats = menu.get("menu_categories", [])

    def price(it):
        p = it.get("price")
        return p if isinstance(p, (int, float)) and p > 0 else None

    # family: cheapest L pizza from the base-pizza categories (excludes the
    # personal 7.5"/S size and the XL/16"/giant size).
    fam = []
    for c in cats:
        if c.get("hidden_category"):
            continue
        cn = _ph_name(c)
        if "פיצות" in cn and ("דקות" in cn or "עבות" in cn or "pan" in cn.lower()):
            for iid in c.get("items", []):
                it = items.get(iid)
                if not it:
                    continue
                n, p = _ph_name(it), price(it)
                if p is None:
                    continue
                if any(s in n for s in ["7.5", "אישי", "אישית"]) or n.strip().endswith(" S"):
                    continue
                if "XL" in n or "16" in n or "ענקית" in n:
                    continue
                fam.append(p)

    # single: one family pizza + garlic bread + drink, standard (non-promo) item.
    sing = []
    for it in items.values():
        n, p = _ph_name(it), price(it)
        if p is None:
            continue
        if ("משפחתית" in n and "לחם שום" in n and "שתי" in n
                and not n.strip().startswith("2") and "2 " not in n
                and not _ph_is_promo(n) and not _ph_has_embedded_price(n)):
            sing.append(p)

    # double: the plain "2 family pizzas" item (no extras, no promo prefix).
    dbl = []
    for it in items.values():
        n, p = _ph_name(it), price(it)
        if p is None:
            continue
        if (n.strip().startswith("2 משפחתיות") and "+" not in n
                and not _ph_is_promo(n) and not _ph_has_embedded_price(n)):
            dbl.append(p)

    return {"family": min(fam) if fam else None,
            "meal_single": min(sing) if sing else None,
            "meal_double": min(dbl) if dbl else None}


# ── Domino's ──────────────────────────────────────────────────────────────────

def _dominos_branch_count():
    """Get branch count quickly via the Dominos REST API (no browser needed)."""
    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": UA, "Content-Type": "application/json",
            "Accept": "application/json", "Origin": "https://www.dominos.co.il",
            "Referer": "https://www.dominos.co.il/", "Accept-Language": "he-IL,he;q=0.9",
        })
        n = [1]
        def call(ep, payload=None):
            if payload is None: payload = {}
            payload["requestNum"] = n[0]; n[0] += 1
            return sess.post(f"https://api.dominos.co.il/{ep}", json=payload, timeout=15).json()

        data = call("connect", {"lang":"he","hardware":"PC","runtime":"browser",
                                "appVersion":"1.16.3","browserType":"Chrome","os":"Windows",
                                "deviceModel":"","referrer":"","url":"https://www.dominos.co.il/"})
        token = data.get("data", {}).get("accessToken", "")
        if not token:
            return None, None
        sess.headers["token"] = token
        call("setLang", {"lang": "he"})
        stores = call("getStoreList").get("data", [])
        open_stores = [s for s in stores if s.get("isOpen")]
        return len(open_stores), open_stores
    except Exception:
        return None, None


def _dominos_api_prices():
    """
    Fallback: get Dominos prices via the REST API.
    Pickup: selectPickupStore → getMenu  (accurate)
    Delivery: getAddressSuggestions → selectDeliveryAddress → getMenu (best-effort)
    """
    r = {"pu": _empty_prices(), "dlv": _empty_prices()}
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA, "Content-Type": "application/json",
        "Accept": "application/json", "Origin": "https://www.dominos.co.il",
        "Referer": "https://www.dominos.co.il/", "Accept-Language": "he-IL,he;q=0.9",
    })
    n = [1]
    def call(ep, payload=None):
        if payload is None: payload = {}
        payload["requestNum"] = n[0]; n[0] += 1
        return sess.post(f"https://api.dominos.co.il/{ep}", json=payload, timeout=20).json()

    try:
        data = call("connect", {"lang":"he","hardware":"PC","runtime":"browser",
                                "appVersion":"1.16.3","browserType":"Chrome","os":"Windows",
                                "deviceModel":"","referrer":"","url":"https://www.dominos.co.il/"})
        token = data.get("data", {}).get("accessToken", "")
        if not token:
            return r
        sess.headers["token"] = token
        call("setLang", {"lang": "he"})
        call("getCustomerDetails", {"gpsstatus": "off", "url": "https://www.dominos.co.il/"})
        call("getGlobalParamsForFe")
        call("getOrderingStatus")

        stores = call("getStoreList").get("data", [])
        open_stores = [s for s in stores if s.get("isOpen")]
        if not open_stores:
            return r

        # Prefer a Tel Aviv branch among the open ones; else fall back to the first open store.
        tlv_open = [s for s in open_stores if "Tel-Aviv" in (s.get("cityUrl") or "")]
        chosen_store = tlv_open[0] if tlv_open else open_stores[0]

        # Pickup: select the chosen store
        call("selectSubService", {"subService": "pu"})
        call("selectPickupStore", {"storeId": str(chosen_store["id"]), "MenuId": "digitalMenu"})
        menu_pu = call("getMenu", {"MenuId": "digitalMenu"})
        if menu_pu.get("status") == "success":
            pairs_pu = walk_json_prices(menu_pu.get("data", {}))
            # DEBUG: show all pairs classified as family
            fam_pairs = [(p, c) for p, c in pairs_pu if kw_match(c.lower(), FAMILY_KW)
                         and not (kw_match(c.lower(), MEAL_KW) and kw_match(c.lower(), SINGLE_KW))]
            print(f"    [DOM family pairs] {fam_pairs[:10]}")
            r["pu"].update(classify_prices(pairs_pu))

        # Delivery: try address-based session
        call("selectSubService", {"subService": "dlv"})
        # Try to get address suggestions for a known central address
        SEARCH = TLV_ADDRESS
        for suggest_ep in ["getAddressSuggestions", "addressSuggestions", "searchAddress"]:
            try:
                sugg = call(suggest_ep, {"searchTerm": SEARCH, "lang": "he"})
                addrs = sugg.get("data", [])
                if addrs:
                    addr = addrs[0]
                    addr_id = addr.get("id") or addr.get("addressId") or addr.get("addressID")
                    for select_ep in ["selectDeliveryAddress", "setDeliveryAddress", "updateDeliveryAddress"]:
                        try:
                            call(select_ep, {"addressId": addr_id, "lang": "he"})
                            break
                        except Exception:
                            pass
                    break
            except Exception:
                pass

        menu_dlv = call("getMenu", {"MenuId": "digitalMenu"})
        if menu_dlv.get("status") == "success":
            r["dlv"].update(classify_prices(walk_json_prices(menu_dlv.get("data", {}))))

    except Exception:
        pass
    return r


def scrape_dominos(pw):
    """
    Scrape Dominos in a VISIBLE Chrome window (headless=False bypasses bot-detection).
    Navigate the real ordering flow for pickup and delivery separately.
    Falls back to REST API if Playwright navigation fails.
    """
    DEBUG_DIR = Path(__file__).parent / "data"
    r = {"pu": _empty_prices(), "dlv": _empty_prices(), "error": None}
    captured = {}
    current_svc = [None]
    api_urls_seen = []

    STEALTH = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};"

    browser = pw.chromium.launch(
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled",
              "--no-sandbox", "--start-minimized"],
    )
    ctx = browser.new_context(
        locale="he-IL", timezone_id="Asia/Jerusalem",
        viewport={"width": 1440, "height": 900}, user_agent=UA,
    )
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()

    def on_response(resp):
        if "api.dominos.co.il" in resp.url:
            short = resp.url.split("?")[0].split("/")[-1]
            if short not in api_urls_seen:
                api_urls_seen.append(short)
            svc = current_svc[0]
            if svc and ("getMenu" in resp.url or "menu" in resp.url.lower()):
                try:
                    body = resp.json()
                    if body.get("status") == "success" and svc not in captured:
                        captured[svc] = body.get("data", {})
                        print(f"    [DOM] captured getMenu for {svc} ✓")
                except Exception:
                    pass

    page.on("response", on_response)

    def screenshot(name):
        try:
            page.screenshot(path=str(DEBUG_DIR / f"dom_debug_{name}.png"))
        except Exception:
            pass

    def click_any(*selectors, timeout=4000):
        for sel in selectors:
            try:
                page.click(sel, timeout=timeout)
                return True
            except Exception:
                pass
        return False

    def js_click(*texts):
        for text in texts:
            try:
                ok = page.evaluate(f"""() => {{
                    const el = [...document.querySelectorAll('button,a,div,span,p')]
                        .find(e => e.offsetParent !== null && (e.innerText||'').includes('{text}'));
                    if (el) {{ el.dispatchEvent(new MouseEvent('click',{{bubbles:true,cancelable:true}})); return true; }}
                    return false;
                }}""")
                if ok:
                    return True
            except Exception:
                pass
        return False

    def click_branch_preferring_city(city, selectors):
        """Try to click a branch row/button whose visible text mentions `city`.
        Falls back to the first matching selector if no city-specific row is found."""
        try:
            found = page.evaluate(f"""(city) => {{
                const rows = [...document.querySelectorAll('li,[class*="store"],[class*="Store"],[class*="branch"]')]
                    .filter(e => e.offsetParent !== null);
                const row = rows.find(e => (e.innerText||'').includes(city));
                if (!row) return false;
                const btn = row.querySelector('button') || row;
                btn.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}}));
                return true;
            }}""", city)
            if found:
                return True
        except Exception:
            pass
        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=4000)
                page.locator(sel).first.click(timeout=3000)
                return True
            except Exception:
                pass
        return False

    def log_buttons():
        try:
            btns = page.evaluate("""() =>
                [...document.querySelectorAll('button,a,[role="button"]')]
                .filter(e => e.offsetParent !== null)
                .map(e => (e.innerText||e.getAttribute('aria-label')||e.className||'?').trim().slice(0,60))
                .filter(t => t.length > 0)
                .slice(0, 20)
            """)
            print(f"    [DOM] visible buttons: {btns}")
        except Exception:
            pass

    def wait_for_page():
        """Wait for page to be interactive."""
        try:
            page.wait_for_load_state("load", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

    def dismiss_ad_popup():
        """Close any promotional popup that appears on homepage load."""
        for sel in ["button.close", "[class*='close-btn']", "[class*='closeBtn']",
                    "[aria-label*='סגור']", "[aria-label*='close']", "button[class*='x-btn']"]:
            try:
                page.click(sel, timeout=2000)
                page.wait_for_timeout(500)
                return True
            except Exception:
                pass
        # If no X button, click outside the popup or press Escape
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass
        return False

    def dismiss_phone_popup():
        """Click 'אני רק רוצה לראות מה יש פה' to skip phone number / proceed as guest."""
        for text in ["אני רק רוצה לראות מה יש פה", "רק לראות", "דלג", "אורח", "ללא התחברות"]:
            try:
                page.get_by_text(text, exact=False).first.click(timeout=3000)
                page.wait_for_timeout(1500)
                print(f"    [DOM] dismissed phone popup via '{text}'")
                return True
            except Exception:
                pass
        if js_click("אני רק רוצה לראות", "רק לראות", "דלג", "אורח"):
            page.wait_for_timeout(1500)
            return True
        return False

    def dismiss_kosher_popup():
        """Click 'כל הסניפים' on the kosher-filter popup."""
        for text in ["כל הסניפים", "הכל", "כולם"]:
            try:
                page.get_by_text(text, exact=False).first.click(timeout=3000)
                page.wait_for_timeout(1500)
                print(f"    [DOM] dismissed kosher popup via '{text}'")
                return True
            except Exception:
                pass
        if js_click("כל הסניפים", "הכל"):
            page.wait_for_timeout(1500)
            return True
        return False

    def open_order_modal():
        """Click the main CTA to open the service-selection modal."""
        log_buttons()
        # Try standard click
        for strategy in [
            lambda: page.get_by_text("הזמן עכשיו", exact=False).first.click(timeout=5000),
            lambda: page.get_by_text("להזמנה", exact=False).first.click(timeout=3000),
            lambda: page.get_by_role("button", name=re.compile(r"הזמן|הזמנ|order", re.I)).first.click(timeout=3000),
            lambda: js_click("הזמן עכשיו", "להזמנה", "הזמנה"),
            lambda: page.mouse.click(720, 450),  # center of page - usually where CTA is
        ]:
            try:
                strategy()
                page.wait_for_timeout(2000)
                # Check if modal appeared
                for modal_text in ["איסוף עצמי", "משלוח", "לאיסוף", "לבחור סניף"]:
                    try:
                        page.wait_for_selector(f"text={modal_text}", timeout=3000)
                        return True
                    except Exception:
                        pass
            except Exception:
                pass
        return False

    def navigate_service(service, addr=None):
        label = "pu" if service == "pu" else "dlv"
        current_svc[0] = service

        try:
            print(f"    [DOM {label}] loading homepage...")
            page.goto("https://www.dominos.co.il/", timeout=40000, wait_until="load")
            wait_for_page()
            screenshot(f"{label}_1_homepage")
            print(f"    [DOM {label}] page loaded. api calls: {api_urls_seen}")

            # Step 1: open service modal (might need to dismiss ad popup first)
            modal_opened = open_order_modal()
            if not modal_opened:
                # Try dismissing ad popup first, then re-open
                dismiss_ad_popup()
                page.wait_for_timeout(1000)
                modal_opened = open_order_modal()
            screenshot(f"{label}_2_modal")
            page.wait_for_timeout(1500)
            print(f"    [DOM {label}] service modal visible: {modal_opened}")
            log_buttons()

            # Step 2: pick service type
            if service == "pu":
                ok = click_any("text=איסוף עצמי", "button:has-text('איסוף')",
                               "[class*='takeaway']", "[class*='pickup']", timeout=5000)
                if not ok:
                    ok = js_click("איסוף עצמי", "איסוף")
                print(f"    [DOM {label}] clicked pickup: {ok}")
                screenshot(f"{label}_3_after_pickup_btn")
                page.wait_for_timeout(3000)
                log_buttons()

                # Step 3a: select a Tel Aviv branch (fall back to first branch shown)
                branch_clicked = click_branch_preferring_city(TLV_CITY,
                    ["[class*='storeItem'] button", "[class*='store-item'] button",
                     "[class*='storeCard'] button", "[class*='StoreCard'] button",
                     "[class*='store-card']", "li[class*='store'] button",
                     "li button", "[data-testid*='store']"])
                if not branch_clicked:
                    js_click("לחץ על מנת לבחור", "לחץ לבחירה", "בחר סניף", "בחר")
                print(f"    [DOM {label}] branch clicked: {branch_clicked}")
                page.wait_for_timeout(3000)
                screenshot(f"{label}_4_after_branch")

                # Dismiss phone popup → guest mode
                dismiss_phone_popup()
                screenshot(f"{label}_5_after_phone_dismiss")

                # Dismiss kosher popup → all branches
                dismiss_kosher_popup()
                screenshot(f"{label}_6_after_kosher")

                # Now a branch list should appear → click first branch
                page.wait_for_timeout(2000)
                log_buttons()
                branch2_clicked = click_branch_preferring_city(TLV_CITY,
                    ["[class*='storeItem'] button", "[class*='store-item'] button",
                     "[class*='storeCard'] button", "[class*='StoreCard'] button",
                     "li[class*='store'] button", "li button"])
                if not branch2_clicked:
                    js_click("לחץ על מנת לבחור", "בחר", "הזמן")
                print(f"    [DOM {label}] branch2 clicked: {branch2_clicked}")
                page.wait_for_timeout(10000)
                screenshot(f"{label}_7_menu")

            else:  # delivery
                ok = click_any("text=משלוח", "button:has-text('משלוח')",
                               "[class*='delivery']", timeout=5000)
                if not ok:
                    ok = js_click("משלוח")
                print(f"    [DOM {label}] clicked delivery: {ok}")
                page.wait_for_timeout(2000)
                screenshot(f"{label}_3_after_dlv_btn")

                # Step 3: enter delivery address — input appears inline after clicking משלוח
                ADDR = addr or TLV_ADDRESS
                addr_filled = False
                # Wait for ANY input to become visible
                try:
                    page.wait_for_selector("input", timeout=5000)
                except Exception:
                    pass
                for sel in ["input[placeholder*='כתובת']", "input[placeholder*='רחוב']",
                            "input[placeholder*='חפש']", "input[placeholder*='הזן']",
                            "[class*='address'] input", "[class*='Address'] input",
                            "input[type='search']", "input[type='text']", "input"]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=3000):
                            el.fill(ADDR, timeout=3000)
                            page.wait_for_timeout(2000)
                            screenshot(f"{label}_4_addr_typed")
                            # Try clicking first autocomplete suggestion
                            try:
                                page.wait_for_selector("[class*='suggestion'],[class*='autocomplete'] li,ul li", timeout=3000)
                                page.locator("[class*='suggestion'],[class*='autocomplete'] li,ul li").first.click(timeout=2000)
                            except Exception:
                                page.keyboard.press("ArrowDown")
                                page.wait_for_timeout(500)
                                page.keyboard.press("Enter")
                            addr_filled = True
                            break
                    except Exception:
                        pass
                print(f"    [DOM {label}] address filled: {addr_filled}")
                page.wait_for_timeout(3000)
                screenshot(f"{label}_5_after_addr")

                # Dismiss phone popup + kosher popup
                dismiss_phone_popup()
                screenshot(f"{label}_6_after_phone_dismiss")
                dismiss_kosher_popup()
                page.wait_for_timeout(10000)
                screenshot(f"{label}_7_menu")

        except Exception as e:
            print(f"    [DOM {label}] nav error: {e}")
            screenshot(f"{label}_error")

        got = service in captured
        print(f"    [DOM {label}] captured: {got}. api urls seen: {api_urls_seen}")
        return got

    # ── Pickup ──
    navigate_service("pu")
    if "pu" in captured:
        r["pu"].update(classify_prices(walk_json_prices(captured["pu"])))
        print("    [DOM pu] Playwright OK ✓")
    else:
        print("    [DOM pu] Playwright failed → API fallback")

    # ── Delivery ──
    navigate_service("dlv", addr=TLV_ADDRESS)
    if "dlv" in captured:
        r["dlv"].update(classify_prices(walk_json_prices(captured["dlv"])))
        print("    [DOM dlv] Playwright OK ✓")
    else:
        print("    [DOM dlv] Playwright failed → API fallback")

    browser.close()

    # ── API fallback for missing services ──
    pu_miss = all(v is None for v in r["pu"].values())
    dlv_miss = all(v is None for v in r["dlv"].values())
    if pu_miss:
        api = _dominos_api_prices()
        if any(v is not None for v in api["pu"].values()):
            r["pu"] = api["pu"]
    # NOTE: delivery is intentionally left empty ("—"). Domino's delivery has a
    # different (marked-up) price list this scraper can't reach reliably yet —
    # and the API's delivery getMenu silently returns the *pickup* store menu
    # when no delivery address is set, so we must not trust it as "delivery".

    return r


# ── Pizza Hut (Atmos SPA — Playwright + route intercept) ──────────────────────

def _pizzahut_branch_count():
    """Count branches from the static branches page (WordPress, no JS needed)."""
    try:
        import re as _re
        resp = requests.get("https://www.pizzahut.co.il/branches",
                            headers={"User-Agent": UA}, timeout=15)
        urls = set(_re.findall(
            r'href="https://www\.pizzahut\.co\.il/branch/[^/"]+/"', resp.text))
        return len(urls) if len(urls) > 10 else None
    except Exception:
        return None


def scrape_pizzahut(page):
    r = {"pu": _empty_prices(), "dlv": _empty_prices(), "error": None}
    dlv_data = {}
    pu_data = {}
    current_menu = [None]  # tracks which menu loaded last: 'dlv' or 'pu'

    branch_count = [_pizzahut_branch_count()]

    def handle_response(response):
        try:
            url = response.url
            if "getMenu" in url:
                body = response.json()
                result = body.get("result", {})
                if isinstance(result, dict) and "errorCode" not in result:
                    if current_menu[0] == "pu":
                        pu_data.update(result)
                    else:
                        dlv_data.update(result)
        except Exception:
            pass

    page.on("response", handle_response)

    try:
        # Load homepage first — triggers the full restaurant-list API call
        page.goto("https://order.pizzahut.co.il/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        current_menu[0] = "dlv"
        page.goto("https://order.pizzahut.co.il/27/menu", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        if dlv_data:
            prices = classify_pizzahut(dlv_data)
        else:
            # Fallback: parse rendered DOM
            prices = {k: v for k, v in _pizzahut_dom(page).items()
                      if k in ("family", "meal_single", "meal_double")}

        # Pizza Hut prices are identical for pickup and delivery (only a delivery
        # fee differs), so the one captured menu populates both services.
        r["dlv"].update(prices)
        r["pu"].update(prices)

        if branch_count[0]:
            r["branch_count"] = branch_count[0]

    except Exception as e:
        r["error"] = str(e)[:120]
    return r


def _pizzahut_dom(page):
    """Fallback: navigate through DOM to extract prices."""
    r = {"family": None, "meal_single": None, "meal_double": None}

    def all_price_items():
        return page.evaluate("""() => {
            const items = [];
            document.querySelectorAll('[class*="item"], [class*="product"], [class*="card"]').forEach(el => {
                const priceEl = el.querySelector('[class*="price"], [class*="Price"]');
                const nameEl  = el.querySelector('[class*="name"], [class*="title"], h2, h3, h4, span');
                if (priceEl && /\\d/.test(priceEl.innerText)) {
                    items.push({name: (nameEl?.innerText||'').trim().slice(0,80),
                                price: priceEl.innerText.trim().slice(0,30)});
                }
            });
            // Also scan modal
            document.querySelectorAll('[role="dialog"] *').forEach(el => {
                const t = el.innerText?.trim();
                if (t && /^[\\d.]+$/.test(t) && parseFloat(t)>20) {
                    const sib = el.previousElementSibling || el.parentElement;
                    items.push({name: (sib?.innerText||'').trim().slice(0,80), price: t});
                }
            });
            return items;
        }""")

    try:
        # Click "הפיצות שלנו" → family pizza
        for sel in ["text=הפיצות שלנו", "text=פיצות", "[class*='nav'] >> text=פיצות"]:
            try:
                page.click(sel, timeout=3000)
                page.wait_for_timeout(1500)
                break
            except Exception:
                pass

        # Click first pizza category
        page.click("text=פיצות עבות", timeout=5000)
        page.wait_for_timeout(1500)

        items = all_price_items()
        # Find L/XL price (family)
        for item in items:
            n = item["name"].lower()
            if "l" in n or "xl" in n or "משפחת" in n:
                p = pick_price(item["price"])
                if p and r["family"] is None:
                    r["family"] = p

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        # Deals — click "מבצעים חמים"
        for sel in ["text=מבצעים", "text=מבצעים חמים"]:
            try:
                page.click(sel, timeout=3000)
                page.wait_for_timeout(1500)
                break
            except Exception:
                pass

        items2 = all_price_items()
        for item in items2:
            n = item["name"]
            p = pick_price(item["price"])
            if not p:
                continue
            if r["meal_double"] is None and ("2 משפחתי" in n or "שתי פיצות" in n or "ל-2" in n):
                r["meal_double"] = p
            elif r["meal_single"] is None and ("1 משפחתי" in n or "פיצה + " in n or "ל-1" in n):
                r["meal_single"] = p

    except Exception as e:
        r["error"] = str(e)[:120]

    return r


# ── Papa John's (React SPA — Chrome channel, UI flow, text parsing) ────────────

def _pj_parse_text_lines(lines):
    """
    Parse price lines extracted from the Papa John's /shop/ menu page.
    Typical lines:
      'פיצה L קלאסית ב-64.9 ₪ באיסוף עצמי'            -> family
      'פיצה L קלאסית + תוספת + 2 פחיות ב-92 ₪'         -> meal_single
      'פיצה L קלאסית + מנה נלווית ב 94 ₪'              -> meal_single
      "2 פיצות L קלאסיות + שתיה 1.5 ל' ב-138 ₪"        -> meal_double
      '2 פיצות קלאסיות L ב 125 ₪'                      -> meal_double
    """
    family, meal_single, meal_double = [], [], []

    for line in lines:
        line = line.strip()
        nums = [float(m.replace(",", ".")) for m in re.findall(r"\d+(?:[.,]\d{1,2})?", line)
                if 20 < float(m.replace(",", ".")) < 800]
        if not nums:
            continue
        price = nums[-1]

        if "2 פיצות" in line or "שתי פיצות" in line:
            meal_double.append(price)
        elif ("פיצה L" in line or "פיצה l" in line.lower()) and "+" not in line:
            family.append(price)
        elif ("פיצה L" in line or "פיצה l" in line.lower()) and "+" in line:
            meal_single.append(price)

    def pick(lst):
        return sorted(lst)[0] if lst else None

    return {"family": pick(family), "meal_single": pick(meal_single), "meal_double": pick(meal_double)}


def scrape_papajohns(page):
    """
    Navigate Papa John's using real Chrome (bypasses Akamai CDN):
      homepage -> 'איסוף עצמי' -> branch list -> 'לחץ על מנת להתחיל הזמנה' -> /shop/ menu
    Parse price lines from page text.
    NOTE: caller must create `page` from a Chrome-channel browser context.
    """
    r = {"pu": _empty_prices(), "dlv": _empty_prices(), "error": None}
    try:
        page.goto("https://www.papajohns.co.il/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        for sel in ["text=הבנתי", "#CybotCookiebotDialogBodyButtonAccept"]:
            try:
                page.click(sel, timeout=2000)
                page.wait_for_timeout(300)
                break
            except Exception:
                pass

        page.click("text=איסוף עצמי", timeout=8000)
        page.wait_for_timeout(3000)

        branch_btns = page.locator("text=לחץ על מנת להתחיל הזמנה").count()
        if branch_btns > 0:
            r["branch_count"] = branch_btns

        # Prefer a Tel Aviv branch; fall back to the second branch (nth=1) — skip
        # אילת (nth=0) which has no VAT — if no Tel Aviv row is found.
        clicked_tlv = page.evaluate(f"""(city) => {{
            const btns = [...document.querySelectorAll('*')]
                .filter(e => e.offsetParent !== null && (e.innerText||'').trim() === 'לחץ על מנת להתחיל הזמנה');
            for (const btn of btns) {{
                const row = btn.closest('li,[class*=branch],[class*=store],[class*=item]') || btn.parentElement;
                if (row && (row.innerText||'').includes(city)) {{
                    btn.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}}));
                    return true;
                }}
            }}
            return false;
        }}""", TLV_CITY)
        if not clicked_tlv:
            page.locator("text=לחץ על מנת להתחיל הזמנה").nth(1).click(timeout=8000)
        page.wait_for_timeout(5000)

        all_lines = page.evaluate("""() =>
            (document.body?.innerText||'').split('\\n')
            .map(l=>l.trim()).filter(l=>l && l.length>1 && l.length<300)
        """)

        pu_prices = _pj_parse_text_lines(all_lines)
        r["pu"].update(pu_prices)

        if not any(v is not None for v in pu_prices.values()):
            r["error"] = "מחירים לא נמצאו בטקסט הדף"

    except Exception as e:
        r["error"] = str(e)[:120]

    # Try delivery flow — go back to homepage and click delivery option
    try:
        page.goto("https://www.papajohns.co.il/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        # Dismiss cookie banner again if it reappeared
        for sel in ["text=הבנתי", "#CybotCookiebotDialogBodyButtonAccept"]:
            try: page.click(sel, timeout=1500); break
            except Exception: pass
        # Click delivery option
        clicked = False
        for sel in ["text=הזמנה לבית", "text=משלוח", "text=הזמנה למשלוח",
                    "text=Delivery", "button:has-text('משלוח')", "a:has-text('משלוח')"]:
            try:
                page.click(sel, timeout=3000)
                page.wait_for_timeout(4000)
                clicked = True
                break
            except Exception:
                pass
        if clicked:
            # Try clicking a Tel Aviv branch start button, else the first one shown
            try:
                clicked_tlv = page.evaluate(f"""(city) => {{
                    const btns = [...document.querySelectorAll('*')]
                        .filter(e => e.offsetParent !== null && (e.innerText||'').trim() === 'לחץ על מנת להתחיל הזמנה');
                    for (const btn of btns) {{
                        const row = btn.closest('li,[class*=branch],[class*=store],[class*=item]') || btn.parentElement;
                        if (row && (row.innerText||'').includes(city)) {{
                            btn.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}}));
                            return true;
                        }}
                    }}
                    return false;
                }}""", TLV_CITY)
                if not clicked_tlv:
                    page.locator("text=לחץ על מנת להתחיל הזמנה").nth(0).click(timeout=5000)
                page.wait_for_timeout(4000)
            except Exception:
                pass
            all_lines = page.evaluate("""() =>
                (document.body?.innerText||'').split('\\n')
                .map(l=>l.trim()).filter(l=>l && l.length>1 && l.length<300)
            """)
            dlv_prices = _pj_parse_text_lines(all_lines)
            if any(v is not None for v in dlv_prices.values()):
                r["dlv"].update(dlv_prices)
    except Exception:
        pass

    return r


# ── Main ───────────────────────────────────────────────────────────────────────

def run_scrape(verbose=True):
    now       = datetime.now()
    today     = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    if verbose:
        print(f"[{timestamp}] Starting multi-chain pizza price scrape...")

    entry = {"date": today, "timestamp": timestamp, "chains": {}}

    # ── Branch count via API (fast, before launching browsers) ──
    if verbose: print("  דומינוס - ספירת סניפים (API)...")
    dom_branch_count, dom_open_stores = _dominos_branch_count()

    # ── Playwright chains ──
    STEALTH_JS = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};"
    with sync_playwright() as pw:
        # Standard browser for Pizza Hut
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="he-IL",
            viewport={"width": 1400, "height": 900},
            user_agent=UA,
            extra_http_headers={"Accept-Language": "he-IL,he;q=0.9"},
        )

        # Pizza Hut
        if verbose: print("  פיצה האט (Playwright)...")
        ph_page = ctx.new_page()
        try:
            ph = scrape_pizzahut(ph_page)
        except Exception as e:
            ph = {"pu": _empty_prices(), "dlv": _empty_prices(), "error": str(e)[:120]}
        finally:
            ph_page.close()
        browser.close()
        # If pickup prices missing, copy from delivery (same prices)
        if any(v is not None for v in ph["dlv"].values()) and all(v is None for v in ph["pu"].values()):
            ph["pu"] = dict(ph["dlv"])
        entry["chains"]["pizzahut"] = ph
        if verbose: _log(ph, "פיצה האט")

        # Chrome channel browser for Dominos + Papa John's (bypasses WAF/Akamai)
        chrome_browser = pw.chromium.launch(
            channel="chrome", headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        chrome_ctx = chrome_browser.new_context(
            locale="he-IL", timezone_id="Asia/Jerusalem",
            viewport={"width": 1440, "height": 900}, user_agent=UA,
        )
        chrome_ctx.add_init_script(STEALTH_JS)

        # Dominos — runs its own headless=False browser internally
        if verbose: print("  דומינוס (visible Chrome)...")
        try:
            dom = scrape_dominos(pw)
        except Exception as e:
            dom = {"pu": _empty_prices(), "dlv": _empty_prices(), "error": str(e)[:120]}
        if dom_branch_count:
            dom["branch_count"] = dom_branch_count
        elif dom_open_stores is not None and not dom_open_stores:
            dom["error"] = (dom.get("error") or "") + " | כל הסניפים סגורים"
        entry["chains"]["dominos"] = dom
        if verbose: _log(dom, "דומינוס")

        # Papa John's
        if verbose: print("  פאפא ג'ונס (Chrome channel)...")
        pj_page = chrome_ctx.new_page()
        try:
            pj = scrape_papajohns(pj_page)
        except Exception as e:
            pj = {"pu": _empty_prices(), "dlv": _empty_prices(), "error": str(e)[:120]}
        finally:
            pj_page.close()
        chrome_browser.close()
        # If delivery prices missing, copy from pickup (same prices)
        if any(v is not None for v in pj["pu"].values()) and all(v is None for v in pj["dlv"].values()):
            pj["dlv"] = dict(pj["pu"])
        entry["chains"]["papajohns"] = pj
        if verbose: _log(pj, "פאפא ג'ונס")

    # (Wolt is now its own discovery-based tracker — see wolt_scraper.py — not
    #  part of the menu-price comparison.)

    # Save locally (JSON mirror / backup + local dev)
    history = load_history()
    history = [h for h in history if h.get("date") != today]
    history.append(entry)
    history.sort(key=lambda x: x["date"])
    save_history(history)

    if verbose:
        print(f"\n  Saved → {DATA_FILE}")

    # Push to Firestore (no-op if credentials aren't configured)
    try:
        import firestore_sync
        if firestore_sync.push_entry(entry) and verbose:
            print("  Synced → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    if verbose:
        print("Done.")

    return entry


def _log(r, name):
    pu = r.get("pu", {})
    dlv = r.get("dlv", {})
    def fmt(d):
        return f"משפחתית={d.get('family')} ארוחה={d.get('meal_single')} זוגי={d.get('meal_double')}"
    print(f"    {name}: pu=[{fmt(pu)}] dlv=[{fmt(dlv)}]" +
          (f" ⚠ {r['error']}" if r.get("error") else ""))


if __name__ == "__main__":
    run_scrape()
