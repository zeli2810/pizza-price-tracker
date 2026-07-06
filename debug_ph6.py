"""Pizza Hut via Atmos - use pickup flow (no address needed) and capture menu API."""
import sys, io, re, json
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

api_calls = {}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=False)  # visible so we can see what happens
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    def on_resp(resp):
        url = resp.url
        if "atmos.co.il" in url and url not in api_calls:
            try:
                body = resp.text()
                prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
                api_calls[url] = {"body": body, "prices": prices, "status": resp.status}
                short = url.replace("https://api-ns.atmos.co.il/rest/1/", "API/")
                print(f"  [{resp.status}] {short[:90]} ({len(body)}b) prices={prices[:5]}")
            except: pass

    page.on("response", on_resp)

    print("1. Loading order.pizzahut.co.il...")
    page.goto("https://order.pizzahut.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "ph6_01_loaded.png"))
    print(f"   URL: {page.url}")

    # Print all clickable elements
    buttons = page.evaluate("""() => {
        const els = [...document.querySelectorAll('button, a, [role=button], [onclick]')];
        return els.map(e => ({
            tag: e.tagName,
            text: (e.innerText||e.textContent||'').trim().slice(0,60),
            class: (e.className||'').slice(0,50),
            href: e.href || '',
        })).filter(e => e.text).slice(0, 30);
    }""")
    print("\nClickable elements:")
    for el in buttons:
        print(f"  <{el['tag']}> {el['text']!r} class={el['class']!r}")

    # Accept cookie/privacy popup
    print("\n2. Accepting cookie popup...")
    for sel in [
        "button:has-text('אישור')",
        "button:has-text('Accept')",
        ".atmos-button:has-text('אישור')",
        "text=אישור",
    ]:
        try:
            page.click(sel, timeout=2000)
            print(f"   Clicked: {sel}")
            page.wait_for_timeout(1000)
            break
        except: pass

    page.screenshot(path=str(OUT / "ph6_02_after_cookie.png"))

    # Print all buttons again after cookie dismiss
    buttons2 = page.evaluate("""() => {
        const els = [...document.querySelectorAll('button, a, [role=button], div[class*=button]')];
        return els.map(e => ({
            tag: e.tagName,
            text: (e.innerText||e.textContent||'').trim().slice(0,60),
            class: (e.className||'').slice(0,60),
        })).filter(e => e.text.length > 0 && e.text.length < 60).slice(0, 30);
    }""")
    print("\nClickable elements after cookie:")
    for el in buttons2:
        print(f"  <{el['tag']}> {el['text']!r} class={el['class']!r}")

    # Try clicking "איסוף עצמי" (pickup - simpler, no address needed)
    print("\n3. Clicking איסוף עצמי (pickup)...")
    clicked = False
    for sel in [
        "text=איסוף עצמי",
        ":text('איסוף עצמי')",
        "button:has-text('איסוף')",
        "a:has-text('איסוף')",
        "[class*='pickup']",
        "[class*='self']",
        "[class*='takeaway']",
    ]:
        try:
            page.click(sel, timeout=2000)
            print(f"   Clicked: {sel}")
            clicked = True
            page.wait_for_timeout(2000)
            break
        except Exception as e:
            print(f"   Failed {sel}: {str(e)[:60]}")

    if not clicked:
        # Try JS click on element containing the text
        result = page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const t = (el.innerText||'').trim();
                if (t === 'איסוף עצמי' || t === 'משלוח') {
                    el.click();
                    return `Clicked: ${el.tagName} "${t}"`;
                }
            }
            return 'Not found';
        }""")
        print(f"   JS click result: {result}")
        page.wait_for_timeout(2000)

    page.screenshot(path=str(OUT / "ph6_03_after_pickup.png"))
    print(f"   URL: {page.url}")

    # Look for store list
    print("\n4. Looking for store selection...")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "ph6_04_stores.png"))

    stores_text = page.evaluate("() => document.body ? document.body.innerText.slice(0,2000) : ''")
    print(f"   Page text: {stores_text[:500]!r}")

    # Try clicking first store
    for sel in [
        ".store-item:first-child",
        "[class*='store']:first-child",
        "[class*='restaurant']:first-child",
        "li:first-child",
        "button:first-child",
    ]:
        try:
            page.click(sel, timeout=2000)
            print(f"   Clicked store: {sel}")
            page.wait_for_timeout(2000)
            break
        except: pass

    # Navigate to menu if possible
    print("\n5. Navigating to menu...")
    for url in ["https://order.pizzahut.co.il/order/menu", "https://order.pizzahut.co.il/menu"]:
        try:
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            print(f"   Loaded: {page.url}")
            page.screenshot(path=str(OUT / "ph6_05_menu.png"))
            break
        except Exception as e:
            print(f"   {url}: {e}")

    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT / "ph6_06_final.png"))

    final_text = page.evaluate("() => document.body ? document.body.innerText.slice(0,3000) : ''")
    price_lines = [l.strip() for l in final_text.split('\n') if re.search(r'\d{2,3}', l.strip()) and len(l.strip()) < 200]
    print(f"\nNumeric lines from final page ({len(price_lines)}):")
    for l in price_lines[:30]:
        print(f"  {l!r}")

    b.close()

# Summarize API calls
print(f"\n\n=== Atmos API calls ({len(api_calls)}) ===")
for url, info in api_calls.items():
    print(f"\n{url}")
    print(f"  Status: {info['status']}, Size: {len(info['body'])}b, Prices: {info['prices'][:10]}")
    if info['prices']:
        fname = re.sub(r'[^a-z0-9]', '_', url.split('/')[-1].split('?')[0][:40])
        (OUT / f"PH6_{fname}.json").write_text(info["body"], encoding="utf-8")
        print(f"  Saved: PH6_{fname}.json")
        # Print a snippet of the body
        try:
            data = json.loads(info["body"])
            print(f"  Keys: {list(data.keys())[:10]}")
        except:
            print(f"  Body snippet: {info['body'][:200]}")
