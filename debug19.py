"""Inspect /.json Next.js data and verify full scraping flow with open store."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

# Inspect the /.json file
data = json.loads((OUT / "nextjs_.json").read_text(encoding="utf-8"))
print("=== /.json top keys ===")
def show(d, depth=0, max_depth=3):
    if depth > max_depth: return
    if isinstance(d, dict):
        for k, v in list(d.items())[:15]:
            t = type(v).__name__
            preview = json.dumps(v, ensure_ascii=False)[:80] if not isinstance(v, (dict, list)) else ""
            children = f" ({len(v)} items)" if isinstance(v, (dict, list)) else ""
            print("  " * depth + f"'{k}': {t}{children} {preview}")
            if isinstance(v, (dict, list)):
                show(v, depth+1, max_depth)
    elif isinstance(d, list) and d:
        show(d[0], depth, max_depth)

show(data)

# Prices in /.json
prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', json.dumps(data, ensure_ascii=False))
print(f"\nPrices in /.json: {prices[:10]}")

# Now test the full Domino's flow for when stores ARE open (simulate 14:00)
print("\n\n=== Testing full Domino's scraping flow ===")
BASE = "https://api.dominos.co.il"
sess = requests.Session()
sess.headers.update({
    "User-Agent": UA, "Content-Type": "application/json",
    "Accept": "application/json", "Origin": "https://www.dominos.co.il",
    "Referer": "https://www.dominos.co.il/",
})
req_num = [1]
def call(ep, payload=None):
    if payload is None: payload = {}
    payload["requestNum"] = req_num[0]; req_num[0] += 1
    r = sess.post(f"{BASE}/{ep}", json=payload)
    try: return r.json(), r.status_code
    except: return {"raw": r.text[:100]}, r.status_code

# Connect
data, _ = call("connect", {"lang":"he","hardware":"PC","runtime":"browser","appVersion":"1.16.3","browserType":"Chrome","os":"Windows","deviceModel":"","referrer":"","url":"https://www.dominos.co.il/"})
sess.headers["token"] = data["data"]["accessToken"]
call("setLang", {"lang":"he"})

# Get store list - find one that MIGHT be open
stores_resp, _ = call("getStoreList")
stores = stores_resp.get("data", [])
print(f"Total stores: {len(stores)}")

# Show all stores' isOpen status
open_s = [s for s in stores if s.get("isOpen")]
closed_s = [s for s in stores if not s.get("isOpen")]
print(f"Open: {len(open_s)}, Closed: {len(closed_s)}")

# Show opening hours for a few stores
for s in stores[:3]:
    print(f"\n  Store {s['id']} ({s['name']}): isOpen={s.get('isOpen')}")
    hours = s.get("openingHours", [])
    if hours:
        print(f"  Opening hours: {json.dumps(hours, ensure_ascii=False)[:200]}")

# Try selectSubService + selectPickupStore for all stores until one works
print("\nTrying to find an open store for pickup...")
call("selectSubService", {"subService": "pu"})
for s in stores[:20]:
    sid = str(s["id"])
    d, _ = call("selectPickupStore", {"storeId": sid})
    status = d.get("status", "?")
    msg = d.get("message", {})
    if isinstance(msg, dict):
        msg_id = msg.get("id", "")
    else:
        msg_id = str(msg)
    if status == "success":
        print(f"  OPEN: Store {sid} ({s['name']}) - SUCCESS!")
        # Now try getMenu
        d2, _ = call("getMenu", {})
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', json.dumps(d2))
        print(f"  getMenu: {d2.get('status')} prices={prices[:5]} size={len(json.dumps(d2))}")
        if prices:
            (OUT / "DOMINOS_REAL_MENU.json").write_text(json.dumps(d2, ensure_ascii=False, indent=2), encoding="utf-8")
        break
    else:
        print(f"  Store {sid} ({s['name'][:15]}): {msg_id}")
