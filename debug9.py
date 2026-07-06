"""Full Domino's API flow to get menu prices."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
OUT = Path(__file__).parent / "data"

BASE = "https://api.dominos.co.il"
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Origin": "https://www.dominos.co.il",
    "Referer": "https://www.dominos.co.il/",
    "Accept-Language": "he-IL,he;q=0.9",
}

sess = requests.Session()
sess.headers.update(HEADERS_BASE)
req_num = [1]

def call(endpoint, payload=None):
    if payload is None:
        payload = {}
    payload["requestNum"] = req_num[0]
    req_num[0] += 1
    r = sess.post(f"{BASE}/{endpoint}", json=payload)
    return r.json(), r

# 1. Connect
print("1. Connect...")
data, r = call("connect", {
    "lang": "he", "hardware": "PC", "runtime": "browser",
    "appVersion": "1.16.3", "browserType": "Chrome", "os": "Windows",
    "deviceModel": "", "referrer": "", "url": "https://www.dominos.co.il/"
})
print(f"   Status: {data.get('status')}")
if data.get("status") == "success":
    token = data["data"].get("accessToken")
    if token:
        sess.headers["Authorization"] = f"Bearer {token}"
        print(f"   Got token: {token[:40]}...")

# 2. setLang
call("setLang", {"lang": "he"})

# 3. getStoreList
print("\n2. Get store list...")
stores_data, _ = call("getStoreList", {})
stores = stores_data.get("data", [])
print(f"   {len(stores)} stores")
store_id = stores[0]["id"] if stores else "501"
store_name = stores[0]["name"] if stores else "unknown"
print(f"   Using store: {store_id} ({store_name})")

# 4. selectSubService (pickup)
print("\n3. selectSubService...")
r4, _ = call("selectSubService", {"subService": "pu"})
print(f"   Status: {r4.get('status')}")

# 5. Try to select the store
print(f"\n4. Trying to select store {store_id}...")
store_endpoints = [
    ("setStore", {"storeId": store_id}),
    ("setStore", {"StoreId": store_id}),
    ("selectStore", {"storeId": store_id}),
    ("setPickupStore", {"storeId": store_id}),
    ("selectPickupStore", {"storeId": store_id}),
    ("setSubService", {"storeId": store_id, "subService": "pu"}),
    ("getOrderFlow", {"storeId": store_id}),
    ("getStoreDetails", {"storeId": store_id}),
    ("getStoreData", {"storeId": store_id}),
]

for ep, payload in store_endpoints:
    try:
        r5 = sess.post(f"{BASE}/{ep}", json={**payload, "requestNum": req_num[0]})
        req_num[0] += 1
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', r5.text)
        status = r5.json().get("status", "?") if r5.headers.get("content-type","").startswith("application/json") else r5.status_code
        print(f"   {ep}: {r5.status_code} status={status} ({len(r5.text)}b) prices={prices[:3]}")
        if prices or len(r5.text) > 2000:
            (OUT / f"menu_{ep}.json").write_text(r5.text, encoding="utf-8")
            print(f"   -> Saved menu_{ep}.json")
    except Exception as e:
        print(f"   {ep}: ERROR {e}")

# 6. Try getMenu endpoints after connect
print("\n5. Trying menu endpoints...")
menu_endpoints = [
    ("getMenuData", {"storeId": store_id}),
    ("getMenuItems", {"storeId": store_id}),
    ("getMenu", {"storeId": store_id}),
    ("getFullMenu", {"storeId": store_id}),
    ("getCatalog", {"storeId": store_id}),
    ("getProducts", {"storeId": store_id}),
    ("getProductList", {"storeId": store_id}),
    ("getPrices", {"storeId": store_id}),
]
for ep, payload in menu_endpoints:
    try:
        r6 = sess.post(f"{BASE}/{ep}", json={**payload, "requestNum": req_num[0]})
        req_num[0] += 1
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', r6.text)
        stat = r6.status_code
        print(f"   {ep}: {stat} ({len(r6.text)}b) prices={prices[:3]}")
        if prices:
            (OUT / f"MENU_{ep}.json").write_text(r6.text, encoding="utf-8")
            print(f"   -> Saved MENU_{ep}.json")
    except Exception as e:
        print(f"   {ep}: ERROR {e}")
