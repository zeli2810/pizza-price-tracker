"""Domino's: check rejected messages and try selectPickupStore then getMenu."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
OUT = Path(__file__).parent / "data"

BASE = "https://api.dominos.co.il"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

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

def call(endpoint, payload=None):
    if payload is None:
        payload = {}
    payload["requestNum"] = req_num[0]
    req_num[0] += 1
    r = sess.post(f"{BASE}/{endpoint}", json=payload)
    try:
        return r.json(), r.status_code, r.text
    except:
        return {}, r.status_code, r.text

# Connect + token
data, _, _ = call("connect", {
    "lang": "he", "hardware": "PC", "runtime": "browser",
    "appVersion": "1.16.3", "browserType": "Chrome", "os": "Windows",
    "deviceModel": "", "referrer": "", "url": "https://www.dominos.co.il/"
})
token = data.get("data", {}).get("accessToken")
sess.headers["token"] = token
call("setLang", {"lang": "he"})

# Get stores
data, _, _ = call("getStoreList", {})
stores = data.get("data", [])
store_id = stores[0]["id"] if stores else "501"

# selectSubService
call("selectSubService", {"subService": "pu"})

# --- Check selectPickupStore with different params ---
print("=== selectPickupStore variations ===")
for payload in [
    {"storeId": store_id},
    {"storeId": int(store_id)},
    {"StoreId": store_id},
    {"storeId": store_id, "subService": "pu"},
    {"id": store_id},
    {"store": store_id},
    {"storeId": store_id, "serviceMethod": "Carryout"},
]:
    d, s, raw = call("selectPickupStore", payload.copy())
    print(f"  {payload}: {s} - {raw[:150]}")

# --- Check getMenu with different params ---
print("\n=== getMenu variations ===")
for payload in [
    {},
    {"storeId": store_id},
    {"lang": "he"},
    {"storeId": store_id, "lang": "he"},
]:
    d, s, raw = call("getMenu", payload.copy())
    print(f"  {payload}: {s} - {raw[:200]}")

# --- Look at what's in the cdn dictionary for menu-related content ---
print("\n=== Checking dictionaryWithAssets for menu info ===")
r = sess.get("https://cdn.dominos.co.il/assets/dictionary/dictionaryWithAssets.v547.json")
d = r.json()
print(f"Top keys: {list(d.keys())}")
for k in d:
    v = d[k]
    if isinstance(v, list):
        print(f"{k}: list of {len(v)}")
        if v and isinstance(v[0], dict):
            print(f"  First item keys: {list(v[0].keys())[:10]}")
    elif isinstance(v, dict):
        print(f"{k}: dict with keys: {list(v.keys())[:10]}")
