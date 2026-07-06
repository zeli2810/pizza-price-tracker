"""Inspect dictionaryWithAssets largeMenus and find MenuId."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
OUT = Path(__file__).parent / "data"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
sess = requests.Session()
sess.headers.update({"User-Agent": UA})

# Download dictionaryWithAssets
r = sess.get("https://cdn.dominos.co.il/assets/dictionary/dictionaryWithAssets.v547.json")
d = r.json()

# Inspect largeMenus
menus = d.get("largeMenus", {})
for menu_name, menu_data in menus.items():
    print(f"\n=== {menu_name} ===")
    if isinstance(menu_data, dict):
        print(f"Keys: {list(menu_data.keys())[:20]}")
        for k, v in menu_data.items():
            if isinstance(v, list):
                print(f"  {k}: list of {len(v)}")
                if v and isinstance(v[0], dict):
                    print(f"    First: {json.dumps(v[0], ensure_ascii=False)[:200]}")
            elif isinstance(v, dict):
                print(f"  {k}: dict keys: {list(v.keys())[:10]}")
            else:
                print(f"  {k}: {str(v)[:100]}")

# Also check the Hebrew BE dictionary for MenuId references
print("\n\n=== Hebrew BE dictionary - price-related keys ===")
r2 = sess.get("https://cdn.dominos.co.il/assets/dictionary/dictionary.he.be.v94.json")
d2 = r2.json()
for k, v in d2.items():
    if any(word in k.lower() for word in ['menu', 'price', 'item', 'product', 'catalog']):
        print(f"  {k}: {str(v)[:100]}")

# Also look for MenuId in the be dictionary
body = json.dumps(d2, ensure_ascii=False)
menu_ids = re.findall(r'"MenuId"[^,}]+', body)
print(f"\nMenuId references: {menu_ids[:5]}")

# Now connect and try getMenu with a MenuId from the store list
print("\n\n=== Try to find MenuId from store data ===")
BASE = "https://api.dominos.co.il"
sess.headers.update({
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.dominos.co.il",
    "Referer": "https://www.dominos.co.il/",
})
req_num = [1]
def call(ep, payload=None):
    if payload is None: payload = {}
    payload["requestNum"] = req_num[0]; req_num[0] += 1
    r = sess.post(f"{BASE}/{ep}", json=payload)
    try: return r.json()
    except: return {"raw": r.text[:200]}

data = call("connect", {"lang":"he","hardware":"PC","runtime":"browser","appVersion":"1.16.3","browserType":"Chrome","os":"Windows","deviceModel":"","referrer":"","url":"https://www.dominos.co.il/"})
token = data.get("data",{}).get("accessToken","")
sess.headers["token"] = token
call("setLang", {"lang": "he"})

stores_resp = call("getStoreList")
stores = stores_resp.get("data", [])
if stores:
    print(f"Store keys: {list(stores[0].keys())}")
    store = stores[0]
    # Look for menu-related fields
    for k, v in store.items():
        if any(word in k.lower() for word in ['menu', 'price', 'catalog', 'id']):
            print(f"  {k}: {v}")

    # Try getMenu with store's menuId if it has one
    menu_id = store.get("menuId") or store.get("MenuId") or store.get("menu_id")
    if menu_id:
        print(f"\nFound menuId: {menu_id}")
        result = call("getMenu", {"menuId": menu_id, "storeId": stores[0]["id"]})
        print(f"getMenu with real menuId: {json.dumps(result, ensure_ascii=False)[:300]}")
    else:
        print("No menuId found in store data")
        # Try with common menu IDs
        for mid in ["1", "2", "main", "501", "default"]:
            result = call("getMenu", {"menuId": mid})
            prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', json.dumps(result))
            print(f"  menuId={mid}: status={result.get('status')} prices={prices[:3]}")
