"""Intercept Dominos getMenu — handle phone popup only, let ordering modals live."""
import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "data"
menu_data = {}
api_log = []

def sc(page, name):
    page.screenshot(path=str(OUT / f"dom_{name}.png"))

def dismiss_phone_popup(page):
    """Remove ONLY the phone number popup (contains a phone input), leave ordering dialogs."""
    removed = page.evaluate("""() => {
        let removed = 0;
        document.querySelectorAll('[role=dialog], [id*=popup], [class*=popup]').forEach(el => {
            if (el.querySelector('input[type=tel], input[type=text], input[type=number]') &&
                (el.innerText||'').includes('נייד')) {
                el.remove(); removed++;
            }
        });
        // Also remove backdrop if popup was removed
        if (removed > 0) {
            document.querySelectorAll('[class*=backdrop],[class*=overlay]').forEach(el => el.remove());
        }
        return removed;
    }""")
    page.wait_for_timeout(300)
    return removed

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(locale="he-IL", viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    def on_resp(resp):
        if "api.dominos.co.il" in resp.url:
            ep = resp.url.split("dominos.co.il/")[-1]
            try:
                body = resp.json()
                st = body.get("status", "?")
                api_log.append(f"<- {ep:30} {st}")
                if ep == "getMenu" and st == "success":
                    menu_data.update(body)
                if ep in ("selectPickupStore", "getMenu"):
                    api_log.append(f"   body: {json.dumps(body, ensure_ascii=False)[:300]}")
            except: pass
    page.on("response", on_resp)

    page.goto("https://www.dominos.co.il/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    n = dismiss_phone_popup(page)
    print(f"Removed {n} phone popup(s)")
    sc(page, "01_clean")

    # Click "איסוף עצמי"
    page.click("text=איסוף עצמי", timeout=5000)
    page.wait_for_timeout(2000)
    sc(page, "02_after_pickup")
    print(f"URL: {page.url}")

    # Dismiss phone popup again if it re-appeared
    dismiss_phone_popup(page)

    # Check what modal appeared
    modal_btns = page.evaluate("""() =>
        Array.from(document.querySelectorAll('[role=dialog] button, [role=dialog] a'))
            .filter(el => el.getBoundingClientRect().height > 0)
            .map(el => ({text: (el.innerText||'').trim().slice(0,40),
                         x: Math.round(el.getBoundingClientRect().x + el.getBoundingClientRect().width/2),
                         y: Math.round(el.getBoundingClientRect().y + el.getBoundingClientRect().height/2)}))
    """)
    print("Modal buttons:", modal_btns)

    # Click "כל הסניפים" if kosher popup appeared
    for btn in modal_btns:
        if any(k in btn['text'] for k in ['כל', 'הסניפים', 'ממשיך', 'המשך', 'אישור']):
            page.mouse.click(btn['x'], btn['y'])
            page.wait_for_timeout(2000)
            print(f"Clicked: {btn['text']!r}")
            break
    else:
        # Try first modal button
        if modal_btns:
            b = modal_btns[0]
            page.mouse.click(b['x'], b['y'])
            page.wait_for_timeout(2000)
            print(f"Clicked first modal btn: {b['text']!r}")

    sc(page, "03_after_kosher")

    # Now look for store search or store list
    inputs = page.evaluate("""() => Array.from(document.querySelectorAll('input'))
        .filter(el => el.getBoundingClientRect().height > 0)
        .map(el => ({placeholder: el.placeholder, y: Math.round(el.getBoundingClientRect().y),
                     x: Math.round(el.getBoundingClientRect().x),
                     w: Math.round(el.getBoundingClientRect().width)}))
    """)
    print("Inputs:", inputs)

    if inputs:
        inp = inputs[0]
        page.mouse.click(inp['x'] + inp['w']//2, inp['y'] + 15)
        page.wait_for_timeout(300)
        page.keyboard.type("תל אביב", delay=50)
        page.wait_for_timeout(2500)
        sc(page, "04_typed")
        # Select first dropdown suggestion
        for sel in ["[class*='option']:first-child", "[class*='suggestion']:first-child",
                    "ul li:first-child", "[role='option']:first-child", "li:first-child"]:
            try:
                page.click(sel, timeout=2000)
                page.wait_for_timeout(2000)
                print(f"Clicked suggestion: {sel}")
                break
            except: pass

    sc(page, "05_after_city")

    # Look for store list items to click
    store_items = page.evaluate("""() => {
        const r = [];
        document.querySelectorAll('[class*=store],[class*=branch],li').forEach(el => {
            const t = (el.innerText||'').trim();
            const rect = el.getBoundingClientRect();
            if (t && /[א-ת]/.test(t) && t.length < 100 && rect.height > 20 && rect.y > 100 && rect.y < 800) {
                r.push({text: t.slice(0,50), x: Math.round(rect.x+rect.width/2), y: Math.round(rect.y+rect.height/2)});
            }
        });
        return r.slice(0,10);
    }""")
    print("Store items:", store_items[:6])

    if store_items:
        item = store_items[0]
        page.mouse.click(item['x'], item['y'])
        page.wait_for_timeout(5000)
        sc(page, "06_store_selected")
        print(f"After store click URL: {page.url}")

    # Navigate to menu
    page.goto("https://www.dominos.co.il/menu", timeout=20000, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    sc(page, "07_menu")
    print(f"Menu URL: {page.url}")

    browser.close()

print("\nAPI log:")
for l in api_log: print(l)
print(f"\nMenu captured: {bool(menu_data)}")
if menu_data:
    s = json.dumps(menu_data.get("data",{}), ensure_ascii=False)
    prices = re.findall(r'"price":\s*"?(\d+(?:\.\d+)?)"?', s)
    print(f"prices: {prices[:20]}")
    (OUT/"dom_menu.json").write_text(json.dumps(menu_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved dom_menu.json")
