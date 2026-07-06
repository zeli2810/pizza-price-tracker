"""Investigate order.pizzahut.co.il ordering platform."""
import sys, io, re, json
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

api_responses = {}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    def on_resp(resp):
        url = resp.url
        if url not in api_responses and any(x in url for x in ['api', 'menu', 'product', 'price', 'catalog', 'item']):
            try:
                body = resp.text()
                prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
                if prices or len(body) > 2000:
                    api_responses[url] = body
                    print(f"  [{resp.status}] {url[:80]} ({len(body)}b) prices={prices[:3]}")
            except: pass

    page.on("response", on_resp)

    # Load order.pizzahut.co.il and wait for full initialization
    page.goto("https://order.pizzahut.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)  # Extra wait for SPA

    page.screenshot(path=str(OUT / "ph4_order_subdomain.png"))
    print(f"URL: {page.url}")
    print(f"Title: {page.title()}")

    # Get visible text
    body = page.evaluate("() => document.body ? document.body.innerText : ''")
    print(f"\nBody text ({len(body)} chars):")
    print(body[:2000])

    # Get all links
    links = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]'))
        .map(a => ({text: (a.innerText||'').trim().slice(0,50), href: a.href}))
        .filter(x => x.href.length > 10)
        .slice(0, 20)""")
    print("\nLinks:")
    for l in links[:15]: print(f"  {l['text']!r} -> {l['href'][:80]}")

    # Save API responses with prices
    print("\n\nAPI responses with prices:")
    for url, body in api_responses.items():
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
        if prices:
            print(f"\n{url[:80]}: {prices[:10]}")
            fname = re.sub(r'[^a-z0-9]', '_', url.split('/')[-1].split('?')[0][:40]) + ".json"
            (OUT / f"PH_{fname}").write_text(body, encoding="utf-8")

    b.close()
