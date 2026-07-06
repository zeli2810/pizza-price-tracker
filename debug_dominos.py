import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

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
token = data.get("data", {}).get("accessToken", "")
print(f"Token: {token[:30]}...")
sess.headers["token"] = token
call("setLang", {"lang": "he"})

stores = call("getStoreList").get("data", [])
print(f"Total stores: {len(stores)}")
open_s = [s for s in stores if s.get("isOpen")]
print(f"Open stores: {len(open_s)}")
for s in stores[:8]:
    print(f"  id={s.get('id')} isOpen={s.get('isOpen')} openHour={s.get('openHour','')} name={str(s.get('name',''))[:25]}")
