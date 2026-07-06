"""Inspect dictionaryWithAssets mainMenu content and try delivery flow."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
OUT = Path(__file__).parent / "data"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
BASE = "https://api.dominos.co.il"
sess = requests.Session()
sess.headers.update({
    "User-Agent": UA, "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.dominos.co.il", "Referer": "https://www.dominos.co.il/",
})

req_num = [1]
def call(ep, payload=None):
    if payload is None: payload = {}
    payload["requestNum"] = req_num[0]; req_num[0] += 1
    r = sess.post(f"{BASE}/{ep}", json=payload)
    try: return r.json(), r.text
    except: return {}, r.text

# 1. dictionaryWithAssets - inspect mainMenu.value.he
print("=== dictionaryWithAssets.mainMenu.value.he ===")
r = requests.get("https://cdn.dominos.co.il/assets/dictionary/dictionaryWithAssets.v547.json")
d = r.json()
main_menu_he = d["largeMenus"]["mainMenu"]["value"]["he"]
print(f"Type: {type(main_menu_he)}")
if isinstance(main_menu_he, dict):
    print(f"Keys: {list(main_menu_he.keys())[:20]}")
    body = json.dumps(main_menu_he, ensure_ascii=False)
    prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
    print(f"Prices in mainMenu.he: {prices[:10]}")
    print(f"Content preview: {body[:500]}")
elif isinstance(main_menu_he, str):
    print(f"Is a string: {main_menu_he[:200]}")
    # Maybe it's a URL to the actual menu
    if main_menu_he.startswith("http"):
        r2 = requests.get(main_menu_he)
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', r2.text)
        print(f"  Fetched URL, prices: {prices[:10]}")

# 2. Connect and try delivery flow
print("\n\n=== Delivery flow ===")
data, _ = call("connect", {"lang":"he","hardware":"PC","runtime":"browser","appVersion":"1.16.3","browserType":"Chrome","os":"Windows","deviceModel":"","referrer":"","url":"https://www.dominos.co.il/"})
token = data.get("data",{}).get("accessToken","")
sess.headers["token"] = token
call("setLang", {"lang":"he"})

# selectSubService with delivery
d2, raw = call("selectSubService", {"subService": "dlv"})
print(f"selectSubService(dlv): {d2.get('status')}")

# Try setDeliveryAddress with a real Tel Aviv address
d3, raw = call("setDeliveryAddress", {"city": "תל אביב", "street": "אבן גבירול", "houseNum": "50"})
print(f"setDeliveryAddress: {d3.get('status')} - {raw[:200]}")

d4, raw = call("setAddress", {"city": "תל אביב", "street": "אבן גבירול", "houseNum": "50"})
print(f"setAddress: {d4.get('status')} - {raw[:200]}")

# Try getting menu in delivery mode
for ep in ["getMenu", "getMenuData", "getOrderFlow"]:
    d5, raw = call(ep, {})
    prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', raw)
    print(f"{ep}: status={d5.get('status')} prices={prices[:5]}")

# 3. Check store URLs from store list
print("\n\n=== Store URLs ===")
stores_resp, _ = call("getStoreList", {})
stores = stores_resp.get("data", [])
if stores:
    for s in stores[:3]:
        print(f"  Store {s['id']} ({s['name']}): url={s.get('url','none')}")

# 4. Check fresh.dominos.co.il
print("\n\n=== fresh.dominos.co.il ===")
try:
    r = requests.get("https://fresh.dominos.co.il", timeout=10,
                    headers={"User-Agent": UA, "Accept-Language": "he-IL"})
    print(f"Status: {r.status_code}, URL: {r.url}")
    prices = re.findall(r'₪\s*(\d+)', r.text)
    print(f"Prices found: {prices[:10]}")
    # Save for inspection
    (OUT / "fresh_dominos.html").write_text(r.text[:10000], encoding="utf-8")
except Exception as e:
    print(f"Error: {e}")
