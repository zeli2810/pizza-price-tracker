"""Find how Domino's auth token is used in requests - check localStorage and request headers."""
import sys, io, json, re
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

connect_token = None
all_request_headers = {}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    # Capture the actual request headers sent to the API
    def on_req(req):
        if "api.dominos.co.il" in req.url:
            ep = req.url.split("/")[-1]
            all_request_headers[ep] = dict(req.headers)

    def on_resp(resp):
        global connect_token
        if "api.dominos.co.il/connect" in resp.url:
            try:
                data = resp.json()
                connect_token = data.get("data", {}).get("accessToken")
            except: pass

    page.on("request", on_req)
    page.on("response", on_resp)

    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    try:
        page.click("div:has-text('תפריט והזמנה')", timeout=3000)
        page.wait_for_timeout(500)
        page.click("button:has-text('איסוף עצמי')", timeout=3000)
        page.wait_for_timeout(3000)
    except: pass

    # Show exact headers for each API call
    print("=== Exact request headers for each API call ===\n")
    for ep, headers in all_request_headers.items():
        print(f"[{ep}]")
        for k, v in sorted(headers.items()):
            if k.lower() not in ('user-agent', 'accept-encoding', 'accept-language', 'connection',
                                 'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform',
                                 'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site'):
                print(f"  {k}: {v[:100]}")
        print()

    # Check localStorage
    print("\n=== localStorage ===")
    storage = page.evaluate("() => Object.entries(localStorage).map(([k,v]) => ({k, v: v.slice(0,100)}))")
    for item in storage:
        print(f"  {item['k']}: {item['v']}")

    # Check sessionStorage
    print("\n=== sessionStorage ===")
    ss = page.evaluate("() => Object.entries(sessionStorage).map(([k,v]) => ({k, v: v.slice(0,100)}))")
    for item in ss:
        print(f"  {item['k']}: {item['v']}")

    # Check cookies
    print("\n=== cookies ===")
    cookies = ctx.cookies(["https://api.dominos.co.il", "https://www.dominos.co.il"])
    for c in cookies:
        print(f"  {c['name']}: {str(c['value'])[:60]}")

    print(f"\nToken from connect: {connect_token[:60] if connect_token else 'None'}...")

    b.close()
