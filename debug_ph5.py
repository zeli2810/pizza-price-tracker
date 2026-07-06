"""Use Atmos API (Pizza Hut's ordering platform) to get menu prices."""
import sys, io, re, json
import requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

ATMOS_BASE = "https://api-ns.atmos.co.il/rest/1"
ATMOS_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Origin": "https://order.pizzahut.co.il",
    "Referer": "https://order.pizzahut.co.il/",
}

sess = requests.Session()
sess.headers.update(ATMOS_HEADERS)

# 1. getBrand
print("1. getBrand...")
r = sess.get(f"{ATMOS_BASE}/restaurants/getBrand", params={"brandId": "pizzahut"})
print(f"   Status: {r.status_code} ({len(r.text)}b)")
try:
    d = r.json()
    print(f"   Keys: {list(d.keys())[:15]}")
    if "data" in d:
        print(f"   data keys: {list(d['data'].keys())[:15]}")
    (OUT / "atmos_getBrand.json").write_text(r.text, encoding="utf-8")
except Exception as e:
    print(f"   Error: {e}, raw: {r.text[:200]}")

# Use Playwright to capture exact API calls during the ordering flow
print("\n2. Navigating ordering flow to capture Atmos API calls...")
api_calls = {}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    def on_resp(resp):
        url = resp.url
        if "atmos.co.il" in url and url not in api_calls:
            try:
                body = resp.text()
                prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
                api_calls[url] = {"body": body, "prices": prices}
                print(f"  [{resp.status}] {url.replace(ATMOS_BASE,'API')[:80]} ({len(body)}b) prices={prices[:3]}")
            except: pass

    page.on("response", on_resp)

    page.goto("https://order.pizzahut.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Accept cookie popup
    try:
        page.click("button:has-text('אישור')", timeout=3000)
        page.wait_for_timeout(1000)
    except: pass

    # Click "משלוח" (delivery)
    try:
        page.click("button:has-text('משלוח'), a:has-text('משלוח')", timeout=4000)
        page.wait_for_timeout(3000)
        print(f"\nAfter clicking משלוח: {page.url}")
    except Exception as e:
        print(f"Could not click משלוח: {e}")

    page.screenshot(path=str(OUT / "ph5_delivery.png"))

    # Try entering an address
    page.wait_for_timeout(2000)
    for sel in ["input[placeholder*='כתובת']", "input[placeholder*='עיר']", "input[type='text']", "input:first-of-type"]:
        try:
            page.fill(sel, "אבן גבירול 100 תל אביב", timeout=2000)
            page.wait_for_timeout(1000)
            break
        except: pass

    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "ph5_address.png"))

    # Look for address suggestions and click first
    try:
        page.click("[role='option']:first-child, li:first-child, .pac-item:first-child", timeout=3000)
        page.wait_for_timeout(3000)
    except: pass

    page.screenshot(path=str(OUT / "ph5_after_address.png"))
    print(f"\nAfter address: {page.url}")

    page.wait_for_timeout(4000)

    # Check for menu/prices
    texts = page.evaluate("""() => {
        const b = document.body;
        return b ? b.innerText.slice(0, 3000) : '';
    }""")
    price_lines = [l.strip() for l in texts.split('\n') if re.search(r'\d{2,3}', l.strip()) and len(l.strip()) < 200]
    print(f"\nPrice/numeric lines ({len(price_lines)}):")
    for l in price_lines[:20]: print(f"  {l!r}")

    b.close()

# Analyze captured API calls
print("\n\n=== API calls with prices ===")
for url, info in api_calls.items():
    if info["prices"]:
        print(f"\n{url}")
        print(f"Prices: {info['prices'][:20]}")
        fname = re.sub(r'[^a-z0-9]', '_', url.split('/')[-1].split('?')[0][:40])
        (OUT / f"PH_MENU_{fname}.json").write_text(info["body"], encoding="utf-8")
        print(f"Saved: PH_MENU_{fname}.json")
