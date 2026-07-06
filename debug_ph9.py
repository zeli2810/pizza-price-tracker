"""Pizza Hut: full pickup flow to reach menu. Intercept catalog/menu API calls."""
import sys, io, re, json
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

api_calls = {}

def on_resp(resp):
    url = resp.url
    if url not in api_calls and ("atmos.co.il" in url or "pizzahut.co.il" in url):
        try:
            body = resp.text()
            prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
            real = [p for p in prices if 30 < float(p) < 600]
            api_calls[url] = {"body": body, "prices": real, "status": resp.status}
            short = url.replace("https://api-ns.atmos.co.il/rest/1/", "API/").replace("https://order.pizzahut.co.il/", "PH/")
            if real or "catalog" in url.lower() or "menu" in url.lower() or "item" in url.lower():
                print(f"  ** [{resp.status}] {short[:90]} ({len(body)}b) prices={real[:5]}")
            else:
                print(f"  [{resp.status}] {short[:90]} ({len(body)}b)")
        except: pass

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()
    page.on("response", on_resp)

    print("=== Step 1: Load ===")
    page.goto("https://order.pizzahut.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    print("=== Step 2: Accept cookie ===")
    try:
        page.click("button:has-text('אישור')", timeout=3000)
        page.wait_for_timeout(1000)
    except: pass

    print("=== Step 3: Click איסוף עצמי ===")
    page.click("text=איסוף עצמי", timeout=5000)
    page.wait_for_timeout(3000)
    print(f"URL: {page.url}")

    print("=== Step 4: Click first branch ===")
    page.click("[class*='branch']:first-child", timeout=5000)
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "ph9_01_branch_clicked.png"))
    print(f"URL: {page.url}")

    # Look for confirm/select button
    btns = page.evaluate("""() => {
        return [...document.querySelectorAll('button, a, [role=button]')]
            .map(e => ({tag: e.tagName, text: (e.innerText||'').trim().slice(0,50), cls: (e.className||'').slice(0,50)}))
            .filter(e => e.text)
            .slice(0, 20);
    }""")
    print("\nButtons after branch click:")
    for bt in btns:
        print(f"  <{bt['tag']}> {bt['text']!r} cls={bt['cls']!r}")

    print("\n=== Step 5: Confirm branch selection ===")
    for sel in [
        "button:has-text('אישור')", "button:has-text('בחר')", "button:has-text('המשך')",
        "button:has-text('הזמנה')", "button:has-text('בחירה')", "button:has-text('תפריט')",
        ".confirm-btn", ".select-btn", "[class*='confirm']", "[class*='select']",
        "button:last-child", ".branch-action button",
    ]:
        try:
            page.click(sel, timeout=2000)
            print(f"  Clicked: {sel}")
            page.wait_for_timeout(3000)
            break
        except: pass

    page.screenshot(path=str(OUT / "ph9_02_after_confirm.png"))
    print(f"URL: {page.url}")
    page.wait_for_timeout(5000)

    print("\n=== Step 6: Wait for menu ===")
    page.screenshot(path=str(OUT / "ph9_03_menu_attempt.png"))
    print(f"URL: {page.url}")

    page_text = page.evaluate("() => document.body ? document.body.innerText.slice(0,2000) : ''")
    price_lines = [l.strip() for l in page_text.split('\n') if re.search(r'\d{2,3}', l.strip()) and len(l.strip()) < 200]
    print(f"\nNumeric lines ({len(price_lines)}):")
    for l in price_lines[:20]:
        print(f"  {l!r}")

    # Also look in the HTML for pizza and price together
    pizza_prices = page.evaluate("""() => {
        const items = [];
        document.querySelectorAll('[class*=item], [class*=product], [class*=pizza]').forEach(el => {
            const txt = (el.innerText||'').trim();
            if (txt && txt.length < 300 && /\\d{2,3}/.test(txt)) {
                items.push(txt.slice(0, 150));
            }
        });
        return items.slice(0, 20);
    }""")
    print("\nPizza/product elements:")
    for it in pizza_prices:
        print(f"  {it!r}")

    b.close()

print("\n\n=== API calls with real prices (30-600) ===")
for url, info in api_calls.items():
    if info["prices"]:
        short = url.replace("https://api-ns.atmos.co.il/rest/1/", "API/").replace("https://order.pizzahut.co.il/", "PH/")
        print(f"\n{short[:100]}")
        print(f"  Status: {info['status']}, Prices: {info['prices'][:20]}")
        fname = re.sub(r'[^a-z0-9]', '_', url.split('/')[-1].split('?')[0][:40])
        fpath = OUT / f"PH9_{fname}.json"
        fpath.write_text(info["body"], encoding="utf-8")
        print(f"  Saved: {fpath.name}")
