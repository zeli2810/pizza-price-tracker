"""Capture exact Domino's API request payloads and use them for direct calls."""
import sys, io, json, re
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

captured = {}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    # Capture request bodies and responses
    def on_request(req):
        if "api.dominos.co.il" in req.url:
            try:
                endpoint = req.url.split("/")[-1]
                body = req.post_data
                captured[f"req_{endpoint}"] = {"url": req.url, "body": body, "headers": dict(req.headers)}
            except: pass

    def on_response(resp):
        if "api.dominos.co.il" in resp.url:
            try:
                endpoint = resp.url.split("/")[-1]
                captured[f"resp_{endpoint}"] = resp.text()
            except: pass

    page.on("request", on_request)
    page.on("response", on_response)

    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    try:
        page.click("div:has-text('תפריט והזמנה')", timeout=3000)
        page.wait_for_timeout(600)
        page.click("button:has-text('איסוף עצמי')", timeout=3000)
        page.wait_for_timeout(3000)
    except: pass

    b.close()

# Show captured request payloads
print("=== CAPTURED API REQUESTS ===\n")
for key, val in captured.items():
    if key.startswith("req_"):
        endpoint = key[4:]
        print(f"\n[{endpoint}]")
        print(f"  URL: {val['url']}")
        print(f"  Body: {val['body']}")
        relevant_headers = {k: v for k, v in val['headers'].items() if k.lower() in
                          ['content-type', 'authorization', 'x-api-key', 'cookie', 'origin']}
        print(f"  Relevant headers: {relevant_headers}")

# Extract connect payload
connect_req = captured.get("req_connect", {})
connect_body_str = connect_req.get("body", "{}")
try:
    connect_body = json.loads(connect_body_str) if connect_body_str else {}
except:
    connect_body = {}

print("\n\n=== USING CAPTURED CONNECT PAYLOAD ===")
print(f"Connect body: {connect_body}")

if connect_body:
    # Try connecting with the real payload
    cookies = {}
    # Extract cookies from the request
    cookie_header = connect_req.get("headers", {}).get("cookie", "")
    if cookie_header:
        for part in cookie_header.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k.strip()] = v.strip()

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Origin": "https://www.dominos.co.il",
        "Referer": "https://www.dominos.co.il/",
    })
    sess.cookies.update(cookies)

    r = sess.post("https://api.dominos.co.il/connect", json=connect_body)
    print(f"\nConnect response: {r.status_code}")
    rdata = r.json()
    print(f"Response: {json.dumps(rdata, ensure_ascii=False)[:300]}")

    if rdata.get("status") == "ok":
        print("\nAuthenticated! Now trying menu endpoints...")
        store_id = "501"
        for ep in ["getMenuData", "getMenu", "getStoreDetails", "getOrderFlow"]:
            r2 = sess.post(f"https://api.dominos.co.il/{ep}", json={"storeId": store_id})
            prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', r2.text)
            print(f"  {ep}: {r2.status_code} ({len(r2.text)}b) prices={prices[:5]}")
