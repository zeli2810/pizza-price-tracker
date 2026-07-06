"""Call Domino's API directly to get store menu and prices."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
OUT = Path(__file__).parent / "data"

BASE = "https://api.dominos.co.il"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.dominos.co.il",
    "Referer": "https://www.dominos.co.il/",
    "Accept-Language": "he-IL,he;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)

# 1. Connect
print("1. Connecting...")
r = session.post(f"{BASE}/connect", json={"lang": "he"})
print(f"   Status: {r.status_code}")
data = r.json()
print(f"   Response: {json.dumps(data, ensure_ascii=False)[:200]}")

# 2. Get store list
print("\n2. Getting store list...")
r2 = session.post(f"{BASE}/getStoreList", json={})
stores = r2.json().get("data", [])
print(f"   {len(stores)} stores found")
if stores:
    print(f"   First store: id={stores[0].get('id')} name={stores[0].get('name')}")

store_id = "501"  # אבן גבירול תל אביב

# 3. Try setStore / getMenuData
print(f"\n3. Trying various menu endpoints for store {store_id}...")
menu_endpoints = [
    ("POST", "/setStore", {"storeId": store_id}),
    ("POST", "/getMenuData", {"storeId": store_id}),
    ("POST", "/getMenuData", {"StoreId": store_id}),
    ("POST", "/getMenuItems", {"storeId": store_id}),
    ("POST", "/getMenu", {"storeId": store_id}),
    ("POST", "/selectStore", {"storeId": store_id}),
    ("GET",  f"/menu/{store_id}", {}),
    ("GET",  f"/store/{store_id}/menu", {}),
    ("POST", "/getStoreMenu", {"storeId": store_id}),
    ("POST", "/getItemList", {"storeId": store_id}),
]

for method, path, payload in menu_endpoints:
    try:
        if method == "POST":
            r3 = session.post(f"{BASE}{path}", json=payload, timeout=8)
        else:
            r3 = session.get(f"{BASE}{path}", timeout=8)
        body = r3.text[:500]
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', r3.text)
        flag = f" *** PRICES: {prices[:5]}" if prices else ""
        print(f"  {method} {path}: {r3.status_code} ({len(r3.text)}b){flag}")
        if prices or (r3.status_code == 200 and len(r3.text) > 1000):
            fname = path.replace("/", "_").strip("_") + ".json"
            (OUT / fname).write_text(r3.text, encoding="utf-8")
            print(f"    -> Saved to {fname}")
    except Exception as e:
        print(f"  {method} {path}: ERROR {e}")

# 4. Check getGlobalParamsForFe
print("\n4. Checking getGlobalParamsForFe...")
r4 = session.post(f"{BASE}/getGlobalParamsForFe", json={})
print(f"   Status: {r4.status_code}")
data4 = r4.json()
if isinstance(data4, dict):
    print(f"   Keys: {list(data4.keys())[:15]}")
    d = data4.get("data", {})
    if isinstance(d, dict):
        print(f"   data keys: {list(d.keys())[:15]}")
