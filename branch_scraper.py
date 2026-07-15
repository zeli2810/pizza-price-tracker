"""
Branch-count tracker: total branches + Tel Aviv branches per pizza chain.

Reality of the sources (investigated 2026-07):
  - Domino's  : clean REST API — total = open-store count, TLV = stores in
                "תל אביב יפו". Scraped live and reliably.
  - Pizza Hut : /branches lists transliterated slugs; Tel Aviv isn't derivable.
  - Papa John's: site is Akamai-protected; count only via the slow order flow.
  - Pizza Shemesh / Story / Prego: JS single-page apps with no static data.

So only Domino's is scraped live. The rest use MANUAL values (seeded from the
figures the user supplied) until per-site scrapers are built. Every record is
tagged with its source ("scraped" / "manual") so the dashboard can show it.

Output: data/branch_counts.json (history) + Firestore branch_counts/{date}.
"""

import json
from pathlib import Path
from datetime import datetime

import requests

from multi_scraper import UA  # importing this also sets UTF-8 stdout on Windows

DATA_FILE = Path(__file__).parent / "data" / "branch_counts.json"

CHAINS = {
    "dominos":   "דומינוס",
    "pizzahut":  "פיצה האט",
    "papajohns": "פאפא ג'ונס",
    "shemesh":   "פיצה שמש",
    "story":     "פיצה סטורי",
    "prego":     "פיצה פרגו",
}

# Manual fallback values (user-provided). Used when a chain can't be scraped.
# Update these here (or later via a scraper) as the real numbers change.
MANUAL = {
    "dominos":   {"total": 64,  "tlv": 7},
    "pizzahut":  {"total": 100, "tlv": None},
    "papajohns": {"total": 43,  "tlv": None},
    "shemesh":   {"total": 100, "tlv": None},
    "story":     {"total": 62,  "tlv": None},
    "prego":     {"total": 25,  "tlv": None},
}


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
    if not total:
        return None
    return {"total": total, "tlv": tlv}


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    return []


def run_scrape(verbose=True):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    entry = {"date": today, "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "chains": {}}

    # Domino's — live scrape, fall back to manual on failure.
    dom = None
    try:
        dom = scrape_dominos_branches()
    except Exception as e:
        if verbose:
            print(f"  Dominos branch scrape failed: {e}")
    if dom:
        entry["chains"]["dominos"] = {**dom, "source": "scraped"}
    else:
        entry["chains"]["dominos"] = {**MANUAL["dominos"], "source": "manual"}

    # The rest — manual values for now.
    for key in CHAINS:
        if key == "dominos":
            continue
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
            db = firestore_sync.get_client()
            db.collection("branch_counts").document(today).set(entry)
            print("  Synced branch counts → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    return entry


if __name__ == "__main__":
    run_scrape()
