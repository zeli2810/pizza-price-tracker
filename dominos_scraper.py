"""
Domino's Israel Price Tracker
Fetches 3 prices from the Domino's API:
  - family pizza (from pizza menu)
  - single-pizza meal deal (from meals menu)
  - double-pizza meal deal (from meals menu)
Run daily at 14:00 via Windows Task Scheduler.
"""
import json
import re
import sys
import io
import requests
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DATA_FILE = Path(__file__).parent / "data" / "dominos_prices.json"
DEBUG_MENU = Path(__file__).parent / "data" / "last_menu_debug.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ── Domino's API ──────────────────────────────────────────────────────────────

def connect_api():
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
        resp = sess.post(f"https://api.dominos.co.il/{ep}", json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json()

    data = call("connect", {
        "lang": "he", "hardware": "PC", "runtime": "browser",
        "appVersion": "1.16.3", "browserType": "Chrome", "os": "Windows",
        "deviceModel": "", "referrer": "", "url": "https://www.dominos.co.il/"
    })
    token = data.get("data", {}).get("accessToken", "")
    if not token:
        raise RuntimeError("connect failed — no token")
    sess.headers["token"] = token
    call("setLang", {"lang": "he"})
    return sess, call


def get_menu(call):
    """Try each open store until we get a successful menu response."""
    stores_data = call("getStoreList")
    stores = stores_data.get("data", [])
    open_stores = [s for s in stores if s.get("isOpen")]

    if not open_stores:
        closed_count = len(stores)
        raise RuntimeError(f"כל {closed_count} הסניפים סגורים כעת")

    call("selectSubService", {"subService": "pu"})

    for store in open_stores[:10]:
        sid = str(store["id"])
        sel = call("selectPickupStore", {"storeId": sid})
        if sel.get("status") != "success":
            continue
        menu_resp = call("getMenu", {})
        if menu_resp.get("status") == "success":
            menu_data = menu_resp.get("data", {})
            print(f"  Got menu from store {sid} ({store.get('name', '')})")
            return menu_data

    raise RuntimeError("לא ניתן לטעון תפריט מאף סניף פתוח")


# ── Price extraction from menu JSON ──────────────────────────────────────────

FAMILY_KW    = ["משפחתית", "family", "large", "xl", "14\"", "14 inch", "לארג'", "l פיצ"]
SINGLE_KW    = ["ארוחה", "סט ל-1", "ל-1", "ל1", "single", "1 פיצה", "פיצה אחת", "meal1", "ארוחת 1"]
DOUBLE_KW    = ["זוגי", "ל-2", "ל2", "שתי פיצות", "2 פיצות", "double", "meal2", "ארוחת 2", "לשניים", "צמד"]
MEAL_CAT_KW  = ["ארוחות", "meal", "deals", "מבצע", "חבילה"]
PIZZA_CAT_KW = ["פיצ", "pizza"]

PRICE_KEYS = {"price", "Price", "unitPrice", "מחיר", "basePrice", "defaultPrice"}


def _is_keyword(text, keywords):
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def _walk_prices(obj, collector, context=""):
    """Recursively walk the menu JSON, collecting (price, context) pairs."""
    if isinstance(obj, dict):
        name = str(obj.get("name", "") or obj.get("Name", "") or obj.get("title", ""))
        ctx = f"{context} | {name}" if name else context
        for k, v in obj.items():
            if k in PRICE_KEYS:
                try:
                    price = float(v)
                    if 20 < price < 600:
                        collector.append((price, ctx))
                except (TypeError, ValueError):
                    pass
            else:
                _walk_prices(v, ctx)  # bug: should pass collector
    elif isinstance(obj, list):
        for item in obj:
            _walk_prices(item, collector, context)


def _walk(obj, collector, context=""):
    if isinstance(obj, dict):
        name = str(obj.get("name") or obj.get("Name") or obj.get("title") or "")
        cat  = str(obj.get("categoryName") or obj.get("category") or "")
        ctx  = " | ".join(filter(None, [context, cat, name]))
        for k, v in obj.items():
            if k in PRICE_KEYS:
                try:
                    price = float(v)
                    if 20 < price < 600:
                        collector.append((price, ctx))
                except (TypeError, ValueError):
                    pass
            _walk(v, collector, ctx)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, collector, context)


def parse_prices(menu_data):
    """Extract family pizza, single-meal, and double-meal prices from menu JSON."""
    collector = []
    _walk(menu_data, collector)

    # Save debug data
    debug = {"collected": [(p, c) for p, c in collector]}
    with open(DEBUG_MENU, "w", encoding="utf-8") as f:
        json.dump(debug, f, ensure_ascii=False, indent=2)

    # Also scan raw JSON text as fallback
    raw_text = json.dumps(menu_data, ensure_ascii=False)

    family_price = None
    single_price = None
    double_price = None

    # Walk collected (price, context) pairs — prefer meal-category context for meals
    meal_singles  = []
    meal_doubles  = []
    family_pizzas = []

    for price, ctx in collector:
        c = ctx.lower()
        is_meal_cat  = _is_keyword(c, MEAL_CAT_KW)
        is_pizza_cat = _is_keyword(c, PIZZA_CAT_KW)
        is_family    = _is_keyword(c, FAMILY_KW)
        is_single    = _is_keyword(c, SINGLE_KW)
        is_double    = _is_keyword(c, DOUBLE_KW)

        if is_meal_cat and is_single:
            meal_singles.append(price)
        if is_meal_cat and is_double:
            meal_doubles.append(price)
        if (is_pizza_cat or not is_meal_cat) and is_family:
            family_pizzas.append(price)

    # Fallback: look for family pizza anywhere
    if not family_pizzas:
        for price, ctx in collector:
            if _is_keyword(ctx, FAMILY_KW):
                family_pizzas.append(price)

    # Fallback for meals: search anywhere
    if not meal_singles:
        for price, ctx in collector:
            if _is_keyword(ctx, SINGLE_KW) and not _is_keyword(ctx, PIZZA_CAT_KW):
                meal_singles.append(price)
    if not meal_doubles:
        for price, ctx in collector:
            if _is_keyword(ctx, DOUBLE_KW):
                meal_doubles.append(price)

    # Pick median/min to avoid outliers
    def best(lst):
        if not lst:
            return None
        lst = sorted(lst)
        return lst[len(lst) // 2]

    family_price = best(family_pizzas)
    single_price = best(meal_singles)
    double_price = best(meal_doubles)

    return {
        "family":      family_price,
        "meal_single": single_price,
        "meal_double": double_price,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run_scrape(verbose=True):
    now       = datetime.now()
    today     = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    if verbose:
        print(f"[{timestamp}] Starting Domino's price scrape...")

    result = {
        "date":      today,
        "timestamp": timestamp,
        "family":    None,
        "meal_single": None,
        "meal_double": None,
        "error":     None,
        "note":      None,
    }

    try:
        _sess, call = connect_api()
        menu_data   = get_menu(call)
        prices      = parse_prices(menu_data)
        result.update(prices)

        if verbose:
            f = result["family"]; s = result["meal_single"]; d = result["meal_double"]
            print(f"  פיצה משפחתית:    {'₪' + str(f) if f else '—'}")
            print(f"  ארוחת פיצה אחת:  {'₪' + str(s) if s else '—'}")
            print(f"  ארוחת שתי פיצות: {'₪' + str(d) if d else '—'}")

    except RuntimeError as e:
        result["error"] = str(e)
        if verbose:
            print(f"  שגיאה: {e}")
    except Exception as e:
        result["error"] = str(e)[:120]
        if verbose:
            print(f"  שגיאה: {e}")

    # Save — replace today's entry
    history = load_history()
    history = [h for h in history if h.get("date") != today]
    history.append(result)
    history.sort(key=lambda x: x["date"])
    save_history(history)

    if verbose:
        print(f"  Saved → {DATA_FILE}")
        print("Done.")

    return result


if __name__ == "__main__":
    run_scrape()
