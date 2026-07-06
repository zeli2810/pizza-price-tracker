"""Use Next.js _next/data/ routes to get Domino's menu data."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

sess = requests.Session()
sess.headers.update({"User-Agent": UA, "Accept-Language": "he-IL,he;q=0.9"})

# Get build ID from homepage
print("Getting Next.js build ID...")
r = sess.get("https://www.dominos.co.il")
build_id = re.search(r'"buildId":"([^"]+)"', r.text)
if build_id:
    build_id = build_id.group(1)
    print(f"Build ID: {build_id}")
else:
    # Try from _next/static
    build_id = "MmFgeoPdfkCF_sVi-fN_H"
    print(f"Using cached build ID: {build_id}")

# Try Next.js data routes
base = f"https://www.dominos.co.il/_next/data/{build_id}/he"
print("\nTrying Next.js data routes:")
routes = [
    "/menu.json",
    "/order.json",
    "/order/store/501.json",
    "/order/store/501/pizza.json",
    "/menu/pizza.json",
    "/order/Ibn-Gvirol.json",
    "/.json",
]
for route in routes:
    url = base + route
    try:
        r2 = sess.get(url, timeout=8)
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', r2.text)
        size = len(r2.text)
        print(f"  {route}: {r2.status_code} ({size}b) prices={prices[:5]}")
        if r2.status_code == 200 and size > 500:
            fname = route.replace("/", "_").strip("_")[:40]
            (OUT / f"nextjs_{fname}").write_text(r2.text, encoding="utf-8")
            print(f"  -> Saved!")
    except Exception as e:
        print(f"  {route}: ERROR {e}")

# Also check the store list for open stores and try their URLs
print("\n\nLooking for open stores...")
import requests
BASE_API = "https://api.dominos.co.il"

def connect_and_get_stores():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA, "Content-Type": "application/json",
        "Accept": "application/json", "Origin": "https://www.dominos.co.il",
        "Referer": "https://www.dominos.co.il/",
    })
    r = s.post(f"{BASE_API}/connect", json={"lang":"he","hardware":"PC","runtime":"browser","appVersion":"1.16.3","browserType":"Chrome","os":"Windows","deviceModel":"","referrer":"","url":"https://www.dominos.co.il/","requestNum":1})
    token = r.json().get("data",{}).get("accessToken","")
    s.headers["token"] = token
    s.post(f"{BASE_API}/setLang", json={"lang":"he","requestNum":2})
    r2 = s.post(f"{BASE_API}/getStoreList", json={"requestNum":3})
    stores = r2.json().get("data",[])
    return s, stores, token

sess_api, stores, token = connect_and_get_stores()
open_stores = [s for s in stores if s.get("isOpen")]
print(f"Open stores: {len(open_stores)}/{len(stores)}")
for s in open_stores[:3]:
    print(f"  id={s['id']} name={s['name']} open={s.get('isOpen')} url={s.get('url')}")

if open_stores:
    store = open_stores[0]
    store_id = store["id"]
    store_url = store.get("url", "")

    # Try to select this store and get menu
    sess_api.post(f"{BASE_API}/selectSubService", json={"subService":"pu","requestNum":4})
    r3 = sess_api.post(f"{BASE_API}/selectPickupStore", json={"storeId": str(store_id), "requestNum":5})
    print(f"\nselectPickupStore(open store {store_id}): {r3.json().get('status')} - {r3.text[:150]}")

    # After selecting an open pickup store, try getMenu
    r4 = sess_api.post(f"{BASE_API}/getMenu", json={"requestNum":6})
    prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', r4.text)
    print(f"getMenu after open store: {r4.status_code} {r4.json().get('status')} prices={prices[:5]} size={len(r4.text)}")
    if prices:
        (OUT / "DOMINOS_MENU_FOUND.json").write_text(r4.text, encoding="utf-8")

    # Try Next.js data route for this store
    route = f"/order/{store_url}.json"
    url = f"https://www.dominos.co.il/_next/data/{build_id}/he" + route
    r5 = sess.get(url)
    print(f"\nNext.js {route}: {r5.status_code} ({len(r5.text)}b)")
    prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', r5.text)
    print(f"Prices: {prices[:5]}")
