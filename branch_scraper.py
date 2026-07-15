"""
Branch-count tracker: total branches + Tel Aviv branches per pizza chain.

Live-scraped (exact, daily):
  - Domino's   : REST API — total open stores + stores in "תל אביב יפו".
  - Pizza Hut  : /branch/ archive — each card shows the branch address, so we
                 count total and those whose address is in Tel Aviv.
  - Papa John's: /branch/ archive (same pattern; a real Chrome browser passes
                 the Akamai check).

Manual fallback (until per-site scrapers are built):
  - Pizza Shemesh / Story / Prego — JS single-page apps; still using the
    user-provided figures (Tel Aviv unknown → null).

Every record is tagged source = "scraped" | "manual".
Output: data/branch_counts.json (history) + Firestore branch_counts/{date}.
"""

import json
from pathlib import Path
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

from multi_scraper import UA  # also sets UTF-8 stdout on Windows

DATA_FILE = Path(__file__).parent / "data" / "branch_counts.json"

CHAINS = {
    "dominos":   "דומינוס",
    "pizzahut":  "פיצה האט",
    "papajohns": "פאפא ג'ונס",
    "shemesh":   "פיצה שמש",
    "story":     "פיצה סטורי",
    "prego":     "פיצה פרגו",
}

# Strings that mark a Tel Aviv address.
TLV_KEYS = ["תל אביב", "תל-אביב", 'ת"א', "ת'א", "תל אביב-יפו", "תל אביב יפו"]

# Manual fallback values (user-provided) for chains we can't scrape yet.
MANUAL = {
    "dominos":   {"total": 64,  "tlv": 7},
    "pizzahut":  {"total": 103, "tlv": 5},
    "papajohns": {"total": 45,  "tlv": 4},
    "shemesh":   {"total": 100, "tlv": None},
    "story":     {"total": 62,  "tlv": 0},   # city list confirms no Tel Aviv branch
    "prego":     {"total": 25,  "tlv": None},
}


def _is_tlv(text):
    return any(k in text for k in TLV_KEYS)


def scrape_dominos_branches():
    """Total open stores + Tel Aviv stores via the Domino's REST API."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
        "Origin": "https://www.dominos.co.il", "Referer": "https://www.dominos.co.il/",
        "Accept-Language": "he-IL,he;q=0.9",
    })
    n = [1]
    def call(ep, p=None):
        p = p or {}; p["requestNum"] = n[0]; n[0] += 1
        return s.post(f"https://api.dominos.co.il/{ep}", json=p, timeout=20).json()
    d = call("connect", {"lang": "he", "hardware": "PC", "runtime": "browser",
                         "appVersion": "1.16.3", "browserType": "Chrome", "os": "Windows",
                         "deviceModel": "", "referrer": "", "url": "https://www.dominos.co.il/"})
    token = d.get("data", {}).get("accessToken", "")
    if not token:
        return None
    s.headers["token"] = token
    call("setLang", {"lang": "he"})
    stores = call("getStoreList").get("data", []) or []
    total = len(stores)
    tlv = None
    try:
        cities = call("getCities").get("data", {}).get("cities", []) or []
        for c in cities:
            if "תל אביב" in (c.get("name") or ""):
                tlv = len(c.get("stores", []) or [])
                break
    except Exception:
        pass
    return {"total": total, "tlv": tlv} if total else None


_WP_EXTRACT = r"""
() => {
  const uniq = {};
  document.querySelectorAll('a[href*="/branch/"]').forEach(a => {
    const h = (a.getAttribute('href') || '').replace(/\/$/, '');
    const m = h.match(/\/branch\/([^\/]+)$/);
    if (!m) return;
    const slug = m[1];
    if (slug === 'page' || slug === 'feed') return;
    const box = a.closest('article,li,[class*=jet],[class*=card]') || a.parentElement || a;
    const t = (box.innerText || a.innerText || '').replace(/\s+/g, ' ').trim();
    if (!uniq[slug] || t.length > uniq[slug].length) uniq[slug] = t;
  });
  return uniq;
}
"""


def scrape_wp_branches(base_url, pw):
    """Total + Tel Aviv count from a WordPress /branch/ archive (address per card)."""
    browser = pw.chromium.launch(
        channel="chrome", headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
    try:
        ctx = browser.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1400, "height": 1200})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()
        page.goto(base_url + "/branch/", timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        cards = {}
        for _ in range(10):
            for slug, txt in (page.evaluate(_WP_EXTRACT) or {}).items():
                if slug not in cards or len(txt) > len(cards[slug]):
                    cards[slug] = txt
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(600)
        if not cards:
            return None
        total = len(cards)
        tlv = sum(1 for t in cards.values() if _is_tlv(t))
        return {"total": total, "tlv": tlv}
    finally:
        browser.close()


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    return []


def run_scrape(verbose=True):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    entry = {"date": today, "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "chains": {}}

    # Domino's — API
    scraped = {}
    try:
        d = scrape_dominos_branches()
        if d:
            scraped["dominos"] = d
    except Exception as e:
        if verbose: print(f"  Dominos scrape failed: {e}")

    # Pizza Hut + Papa John's — WordPress /branch/ archives
    with sync_playwright() as pw:
        for key, base in [("pizzahut", "https://www.pizzahut.co.il"),
                          ("papajohns", "https://www.papajohns.co.il")]:
            try:
                r = scrape_wp_branches(base, pw)
                if r and r["total"]:
                    scraped[key] = r
            except Exception as e:
                if verbose: print(f"  {CHAINS[key]} scrape failed: {e}")

    for key in CHAINS:
        if key in scraped:
            entry["chains"][key] = {**scraped[key], "source": "scraped"}
        else:
            entry["chains"][key] = {**MANUAL[key], "source": "manual"}

    if verbose:
        for k, v in entry["chains"].items():
            print(f"  {CHAINS[k]}: total={v['total']} tlv={v['tlv']} ({v['source']})")

    # Save local history (replace today, keep the rest).
    history = [h for h in load_history() if h.get("date") != today]
    history.append(entry)
    history.sort(key=lambda x: x["date"])
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"  Saved → {DATA_FILE}")

    # Push to Firestore (no-op without credentials).
    try:
        import firestore_sync
        if firestore_sync.is_enabled():
            firestore_sync.get_client().collection("branch_counts").document(today).set(entry)
            print("  Synced branch counts → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    return entry


if __name__ == "__main__":
    run_scrape()
