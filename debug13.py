"""Use the correct 'token' header to call Domino's API and find menu endpoint."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
OUT = Path(__file__).parent / "data"

BASE = "https://api.dominos.co.il"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

HEADERS = {
    "User-Agent": UA,
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.dominos.co.il",
    "Referer": "https://www.dominos.co.il/",
    "Accept-Language": "he-IL,he;q=0.9",
}

sess = requests.Session()
sess.headers.update(HEADERS)
req_num = [1]

def call(endpoint, payload=None, extra_headers=None):
    if payload is None:
        payload = {}
    payload["requestNum"] = req_num[0]
    req_num[0] += 1
    hdrs = {}
    if extra_headers:
        hdrs.update(extra_headers)
    r = sess.post(f"{BASE}/{endpoint}", json=payload, headers=hdrs)
    try:
        return r.json(), r.status_code
    except:
        return {"raw": r.text[:200]}, r.status_code

# 1. Connect and get token
print("1. Connecting...")
data, _ = call("connect", {
    "lang": "he", "hardware": "PC", "runtime": "browser",
    "appVersion": "1.16.3", "browserType": "Chrome", "os": "Windows",
    "deviceModel": "", "referrer": "", "url": "https://www.dominos.co.il/"
})
token = data.get("data", {}).get("accessToken") or data.get("data", {}).get("token")
print(f"   token: {str(token)[:50]}...")
if not token:
    print(f"   Response: {json.dumps(data)[:200]}")
    sys.exit(1)

# Add token to all subsequent requests
TOKEN_HEADER = {"token": token}
sess.headers.update(TOKEN_HEADER)

# 2. setLang
call("setLang", {"lang": "he"})

# 3. getStoreList
print("\n2. getStoreList...")
data, _ = call("getStoreList", {})
stores = data.get("data", [])
print(f"   Stores: {len(stores)}")
store_id = stores[0]["id"] if stores else "501"
print(f"   Using store: {store_id}")

# 4. selectSubService (pickup)
data, _ = call("selectSubService", {"subService": "pu"})
print(f"\n3. selectSubService: {data.get('status')}")

# 5. Check urls.he.v154.json for available endpoints
print("\n4. Checking URL config for menu endpoints...")
try:
    r = sess.get("https://cdn.dominos.co.il/assets/dictionary/urls.he.v154.json")
    urls_data = r.json()
    print(f"   Keys: {list(urls_data.keys())[:15]}")
    # Look for menu/store related URLs
    for k, v in urls_data.items():
        if any(word in k.lower() for word in ['menu', 'store', 'item', 'product', 'catalog', 'select']):
            print(f"   {k}: {v}")
except Exception as e:
    print(f"   Error: {e}")

# 6. Try endpoints with token
print(f"\n5. Trying endpoints with token header for store {store_id}...")
test_endpoints = [
    ("selectStore", {"storeId": store_id}),
    ("getStoreMenu", {"storeId": store_id}),
    ("getMenuData", {"storeId": store_id}),
    ("getMenu", {"storeId": store_id}),
    ("getMenuItems", {"storeId": store_id}),
    ("selectPickupStore", {"storeId": store_id}),
    ("setSelectedPickupStore", {"storeId": store_id}),
    ("getFullMenu", {"storeId": store_id}),
    ("getOrderInfo", {"storeId": store_id}),
    ("getStoreInfo", {"storeId": store_id}),
    ("getProductDetails", {"storeId": store_id}),
    ("getCatalog", {}),
    ("getBasket", {}),
]
for ep, payload in test_endpoints:
    data, status = call(ep, payload)
    body_str = json.dumps(data, ensure_ascii=False)
    prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body_str)
    api_status = data.get("status", "?")
    size = len(body_str)
    print(f"   {ep}: HTTP={status} api={api_status} size={size} prices={prices[:3]}")
    if prices:
        fname = f"DOMINOS_PRICES_{ep}.json"
        (OUT / fname).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"   *** PRICES FOUND! Saved {fname} ***")
