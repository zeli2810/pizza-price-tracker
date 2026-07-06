"""Intercept Domino's API calls to find pricing endpoint."""
import sys, io, json
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

api_calls = []

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    # Capture all XHR/fetch calls
    def on_request(req):
        if req.resource_type in ("xhr", "fetch"):
            api_calls.append({"method": req.method, "url": req.url[:200]})

    def on_response(resp):
        if resp.request.resource_type in ("xhr", "fetch"):
            url = resp.url
            if any(k in url.lower() for k in ["menu", "price", "product", "catalog", "item", "pizza"]):
                try:
                    body = resp.text()
                    if len(body) < 50000:
                        path = OUT / f"api_{url.split('/')[-1].split('?')[0][:40]}.json"
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(body)
                        print(f"Saved API response: {url[:100]} -> {path.name}")
                except Exception:
                    pass

    page.on("request", on_request)
    page.on("response", on_response)

    # Navigate to ordering flow
    print("Loading Domino's...")
    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Click through the ordering flow
    try:
        page.click("div:has-text('תפריט והזמנה')", timeout=3000)
        page.wait_for_timeout(1000)
    except: pass

    try:
        page.click("button:has-text('איסוף עצמי')", timeout=3000)
        page.wait_for_timeout(3000)
    except: pass

    # Try clicking the first branch in whatever list appears
    page.screenshot(path=str(OUT / "dom_flow.png"))

    # All clickable items
    items = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a, button, li, [role=listitem]'))
            .map(el => ({text: (el.innerText||'').trim().slice(0,60), tag: el.tagName, href: el.href||''}))
            .filter(x => x.text.length > 0)
    }""")
    print("\nAll clickable elements:")
    for i in items[:60]:
        print(f"  [{i['tag']}] {i['text']!r}  {i['href'][:60] if i['href'] else ''}")

    print("\n\nAll API calls made:")
    for c in api_calls:
        print(f"  [{c['method']}] {c['url']}")

    b.close()
