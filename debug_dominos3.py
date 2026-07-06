import json, requests, re
from pathlib import Path
from multi_scraper import walk_json_prices, classify_prices, FAMILY_KW, DOUBLE_KW, SINGLE_KW

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
sess = requests.Session()
sess.headers.update({"User-Agent": UA, "Content-Type": "application/json",
                     "Accept": "application/json", "Origin": "https://www.dominos.co.il",
                     "Referer": "https://www.dominos.co.il/", "Accept-Language": "he-IL,he;q=0.9"})
n = [1]
def call(ep, payload=None):
    if payload is None: payload = {}
    payload["requestNum"] = n[0]; n[0] += 1
    resp = sess.post(f"https://api.dominos.co.il/{ep}", json=payload, timeout=20)
    try: return resp.json()
    except: return {"status": "parse_error"}

data = call("connect", {"lang": "he", "hardware": "PC", "runtime": "browser",
                        "appVersion": "1.16.3", "browserType": "Chrome", "os": "Windows",
                        "deviceModel": "", "referrer": "", "url": "https://www.dominos.co.il/"})
sess.headers["token"] = data.get("data", {}).get("accessToken", "")
call("setLang", {"lang": "he"})
call("getCustomerDetails", {"gpsstatus": "off", "url": "https://www.dominos.co.il/"})
call("getGlobalParamsForFe")
call("getOrderingStatus")
stores = call("getStoreList").get("data", [])
open_s = [s for s in stores if s.get("isOpen")]
call("selectSubService", {"subService": "pu"})
call("selectPickupStore", {"storeId": str(open_s[0]["id"]), "MenuId": "digitalMenu"})
menu = call("getMenu", {"MenuId": "digitalMenu"})

pairs = walk_json_prices(menu.get("data", {}))
lines = [f"Total pairs: {len(pairs)}", "All prices (sorted desc):"]
seen = set()
for p, ctx in sorted(pairs, key=lambda x: -x[0]):
    key = f"{p:.1f}|{ctx[:40]}"
    if key not in seen:
        seen.add(key)
        lines.append(f"  {p:7.1f} | {ctx[:100]}")

lines.append(f"\nclassify_prices: {classify_prices(pairs)}")
lines.append("\nFamily matches:")
for p, ctx in pairs:
    if any(k.lower() in ctx.lower() for k in FAMILY_KW):
        lines.append(f"  {p} | {ctx[:80]}")
lines.append("\nDouble matches:")
for p, ctx in pairs:
    if any(k.lower() in ctx.lower() for k in DOUBLE_KW):
        lines.append(f"  {p} | {ctx[:80]}")

out = Path(__file__).parent / "data" / "dominos_debug.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"Done — {len(pairs)} pairs")
