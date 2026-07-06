"""Complete delivery flow in browser - enter address, intercept menu API."""
import sys, io, json, re
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

all_api = {}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    def on_resp(resp):
        url = resp.url
        if "api.dominos.co.il" in url and url not in all_api:
            try:
                body = resp.text()
                all_api[url] = body
                prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
                if prices or len(body) > 3000:
                    ep = url.split("/")[-1]
                    print(f"  [{ep}] {len(body)}b prices={prices[:5]}")
            except: pass

    page.on("response", on_resp)

    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Click "תפריט והזמנה"
    try:
        page.click("div:has-text('תפריט והזמנה')", timeout=3000)
        page.wait_for_timeout(600)
    except: pass

    # Click "משלוח" (delivery, not pickup)
    try:
        page.click("button:has-text('משלוח')", timeout=3000)
        page.wait_for_timeout(2000)
        print("Clicked משלוח")
    except Exception as e:
        print(f"Could not click משלוח: {e}")

    page.screenshot(path=str(OUT / "dom17_step1.png"))

    # Enter address in the address field
    # Look for input field
    inputs = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('input'))
            .map(el => ({type: el.type, placeholder: el.placeholder, id: el.id, name: el.name}))
    }""")
    print("Input fields:", inputs)

    # Try typing in an address
    for sel in ["input[placeholder*='כתובת']", "input[placeholder*='עיר']", "input[name*='address']", "input[type='text']", "input:first-of-type"]:
        try:
            page.fill(sel, "אבן גבירול 100, תל אביב", timeout=2000)
            page.wait_for_timeout(1000)
            print(f"Filled address in {sel}")
            break
        except: pass

    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT / "dom17_step2.png"))

    # Look for address suggestions
    suggestions = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('li, [role=option], .suggestion'))
            .map(el => (el.innerText||'').trim().slice(0,60))
            .filter(t => t.length > 5)
            .slice(0, 10)
    }""")
    print("Address suggestions:", suggestions)

    if suggestions:
        # Click first suggestion
        try:
            page.click("li:first-child, [role=option]:first-child", timeout=2000)
            page.wait_for_timeout(3000)
            print("Clicked first suggestion")
        except: pass

    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "dom17_step3.png"))
    print("\nCurrent URL:", page.url)
    print("Page title:", page.title())

    # Check for menu content
    texts = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText||'').trim();
            if (t && t.length < 200 && !seen.has(t) && t.includes('₪')) {
                seen.add(t); out.push(t);
            }
        });
        return out.slice(0, 20);
    }""")
    print(f"\nPrice texts on page ({len(texts)}):")
    for t in texts[:15]: print(f"  {t!r}")

    # Show all intercepted API calls
    print("\n\nAll API calls:")
    for url, body in all_api.items():
        ep = url.split("/")[-1]
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
        print(f"  {ep}: {len(body)}b prices={prices[:3]}")
        if prices:
            (OUT / f"DOM_PRICES_{ep}.json").write_text(body, encoding="utf-8")

    b.close()
