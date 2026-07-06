import json, requests
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
sess = requests.Session()
sess.headers.update({"User-Agent": UA, "Content-Type": "application/json",
                     "Accept": "application/json", "Origin": "https://www.dominos.co.il",
                     "Referer": "https://www.dominos.co.il/", "Accept-Language": "he-IL,he;q=0.9"})
n = [1]
def call(ep, payload=None):
    if payload is None: payload = {}
    payload["requestNum"] = n[0]; n[0] += 1
    return sess.post(f"https://api.dominos.co.il/{ep}", json=payload, timeout=20).json()

data = call("connect", {"lang": "he", "hardware": "PC", "runtime": "browser",
                        "appVersion": "1.16.3", "browserType": "Chrome", "os": "Windows",
                        "deviceModel": "", "referrer": "", "url": "https://www.dominos.co.il/"})
sess.headers["token"] = data.get("data", {}).get("accessToken", "")
call("setLang", {"lang": "he"})
stores = call("getStoreList").get("data", [])

# Check available subServices per store
lines = []
for s in stores[:5]:
    pts = s.get("promiseTimes", [])
    services = [pt.get("subServiceId") for pt in pts]
    lines.append(f"id={s['id']} name={s.get('name','')[:15]} isOpen={s.get('isOpen')} services={services}")

# Find stores with pickup
pu_stores = [s for s in stores if any(pt.get("subServiceId") == "pu" for pt in s.get("promiseTimes", []))]
dlv_stores = [s for s in stores if any(pt.get("subServiceId") == "dlv" for pt in s.get("promiseTimes", []))]
lines.append(f"\nStores with pickup (pu): {len(pu_stores)}")
lines.append(f"Stores with delivery (dlv): {len(dlv_stores)}")

# Try delivery flow
if dlv_stores:
    call("selectSubService", {"subService": "dlv"})
    res = call("selectPickupStore", {"storeId": str(dlv_stores[0]["id"])})
    lines.append(f"\nWith dlv + selectPickupStore: {json.dumps(res, ensure_ascii=False)[:200]}")

    menu = call("getMenu", {})
    lines.append(f"getMenu status: {menu.get('status')}")
    if menu.get("status") == "success":
        import re
        menu_str = json.dumps(menu.get("data", {}), ensure_ascii=False)
        price_hits = re.findall(r'"price":\s*"?(\d+(?:\.\d+)?)"?', menu_str)
        name_hits  = re.findall(r'"name":\s*"([^"]{2,30})"', menu_str)
        lines.append(f"prices: {price_hits[:20]}")
        lines.append(f"names: {name_hits[:20]}")

out = Path(__file__).parent / "data" / "dominos_debug.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print("Done")
