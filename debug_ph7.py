"""Pizza Hut Atmos - click a specific store and capture menu prices."""
import sys, io, re, json
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

api_calls = {}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    def on_resp(resp):
        url = resp.url
        if ("atmos.co.il" in url or "pizzahut" in url) and url not in api_calls:
            try:
                body = resp.text()
                prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
                api_calls[url] = {"body": body, "prices": prices, "status": resp.status}
                short = url.replace("https://api-ns.atmos.co.il/rest/1/", "API/")
                print(f"  [{resp.status}] {short[:90]} ({len(body)}b) prices={prices[:5]}")
            except: pass

    page.on("response", on_resp)

    # Full flow: cookie -> pickup -> store -> menu
    print("Step 1: Load...")
    page.goto("https://order.pizzahut.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    print("Step 2: Accept cookie...")
    try:
        page.click("button:has-text('אישור')", timeout=3000)
        page.wait_for_timeout(1000)
    except: pass

    print("Step 3: Click pickup...")
    page.click("text=איסוף עצמי", timeout=5000)
    page.wait_for_timeout(3000)
    print(f"  URL: {page.url}")

    # Show store elements
    store_els = page.evaluate("""() => {
        const items = document.querySelectorAll('[class*=branch], [class*=store], [class*=restaurant], li, .list-item');
        return [...items].slice(0,5).map(el => ({
            tag: el.tagName,
            cls: (el.className||'').slice(0,60),
            text: (el.innerText||'').trim().slice(0,80),
        }));
    }""")
    print("\nStore elements:")
    for el in store_els:
        print(f"  <{el['tag']}> cls={el['cls']!r} text={el['text']!r}")

    print("\nStep 4: Click first store...")
    store_clicked = False
    for sel in [
        "[class*='branch']:first-child",
        "[class*='store-item']:first-child",
        ".list-item:first-child",
        "li:first-child",
        "[class*='item']:first-child",
    ]:
        try:
            page.click(sel, timeout=2000)
            print(f"  Clicked: {sel}")
            store_clicked = True
            page.wait_for_timeout(3000)
            break
        except Exception as e:
            print(f"  Failed {sel}: {str(e)[:50]}")

    if not store_clicked:
        # JS click on first store in list by finding א which is an early Hebrew letter
        result = page.evaluate("""() => {
            // Try to find the first store result item
            const candidates = [...document.querySelectorAll('*')].filter(el => {
                const t = (el.innerText||'').trim();
                return t && t.length > 5 && t.length < 100 && /[א-ת]/.test(t);
            });
            // Find items that look like store names (short Hebrew text)
            const stores = candidates.filter(el => {
                const children = el.querySelectorAll('*');
                return children.length < 5;  // leaf-ish node
            });
            if (stores[0]) {
                stores[0].click();
                return `Clicked: "${(stores[0].innerText||'').trim().slice(0,50)}"`;
            }
            return 'Not found';
        }""")
        print(f"  JS click: {result}")
        page.wait_for_timeout(3000)

    page.screenshot(path=str(OUT / "ph7_01_after_store.png"))
    print(f"  URL after store: {page.url}")

    # Wait for menu to load
    print("\nStep 5: Waiting for menu...")
    page.wait_for_timeout(8000)
    page.screenshot(path=str(OUT / "ph7_02_menu.png"))
    print(f"  URL: {page.url}")

    body_text = page.evaluate("() => document.body ? document.body.innerText.slice(0,3000) : ''")
    price_lines = [l.strip() for l in body_text.split('\n') if re.search(r'\d{2,3}', l.strip()) and len(l.strip()) < 200]
    print(f"\nNumeric lines ({len(price_lines)}):")
    for l in price_lines[:30]:
        print(f"  {l!r}")

    b.close()

print(f"\n\n=== Atmos API calls with prices ({sum(1 for v in api_calls.values() if v['prices'])}) ===")
for url, info in api_calls.items():
    print(f"\n{url}")
    print(f"  Status: {info['status']}, Size: {len(info['body'])}b, Prices: {info['prices'][:10]}")
    if info['prices']:
        fname = re.sub(r'[^a-z0-9]', '_', url.split('/')[-1].split('?')[0][:40])
        fpath = OUT / f"PH7_{fname}.json"
        fpath.write_text(info["body"], encoding="utf-8")
        print(f"  Saved: {fpath.name}")
        try:
            data = json.loads(info["body"])
            if isinstance(data, dict):
                print(f"  Keys: {list(data.keys())[:10]}")
        except: pass
