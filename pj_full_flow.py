"""
Full Papa John's ordering flow with Chrome channel.
Flow: Homepage → click 'איסוף עצמי' → select branch → navigate menu → extract prices.
Also takes screenshots for visual OCR.
"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "data"
UA  = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['he-IL','he','en-US']});
Object.defineProperty(navigator, 'plugins',   {get: () => [1,2,3,4,5]});
"""

def sc(page, name):
    p = str(OUT / f"pj_flow_{name}.png")
    page.screenshot(path=p, full_page=False)
    print(f"  📷 {name}")
    return p

def visible_text_with_prices(page):
    return page.evaluate("""() => {
        const lines = (document.body?.innerText || '').split('\\n')
            .map(l => l.trim()).filter(l => l && l.length < 200 && /\\d/.test(l));
        return lines;
    }""")

def dom_prices(page):
    return page.evaluate("""() => {
        const out = [];
        const seen = new Set();
        document.querySelectorAll('*').forEach(el => {
            if (el.children.length > 3) return;
            const t = (el.innerText || '').trim();
            if (!t || t.length > 150 || seen.has(t)) return;
            if (/[₪]/.test(t) || (/\\d{2,3}/.test(t) && /[א-ת]/.test(t))) {
                seen.add(t);
                out.push(t);
            }
        });
        return out;
    }""")

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        channel="chrome", headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    ctx = browser.new_context(
        locale="he-IL", timezone_id="Asia/Jerusalem",
        viewport={"width": 1440, "height": 900},
        user_agent=UA,
    )
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()

    # ── 1. Homepage ───────────────────────────────────────────────────────────
    print("1. Homepage...")
    page.goto("https://www.papajohns.co.il/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Click cookie consent
    for sel in ["button:has-text('הבנתי')", "#CybotCookiebotDialogBodyButtonAccept", "button:has-text('אישור')"]:
        try: page.click(sel, timeout=2000); page.wait_for_timeout(500); break
        except Exception: pass

    # Click "איסוף עצמי"
    for sel in ["text=איסוף עצמי", "button:has-text('איסוף')", "a:has-text('איסוף עצמי')"]:
        try:
            page.click(sel, timeout=4000)
            page.wait_for_timeout(2500)
            print(f"  Clicked: {sel}")
            break
        except Exception: pass

    sc(page, "01_after_pickup_click")
    print(f"  URL: {page.url}")

    # ── 2. Branch selection ───────────────────────────────────────────────────
    print("2. Branch selection...")
    page.wait_for_timeout(1500)
    sc(page, "02_branch_page")

    # Look for branch/store selector inputs or buttons
    branches = page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('input[type=text], input[type=search], select').forEach(el => {
            out.push({tag: el.tagName, type: el.type, placeholder: el.placeholder, id: el.id, name: el.name});
        });
        document.querySelectorAll('button, a').forEach(el => {
            const t = (el.innerText||'').trim();
            if (t && t.length < 40 && /[א-ת]/.test(t)) out.push({tag:'btn', text:t});
        });
        return out.slice(0, 30);
    }""")
    print(f"  Elements: {branches[:15]}")

    # Try to type a city and select branch
    for input_sel in ["input[placeholder*='עיר']", "input[placeholder*='כתובת']", "input[placeholder*='סניף']",
                      "input[type='search']", "input[type='text']"]:
        try:
            page.fill(input_sel, "תל אביב", timeout=3000)
            page.wait_for_timeout(1500)
            sc(page, "03_city_typed")
            # Click first suggestion
            for sug in ["li:first-child", ".suggestion:first-child", "[class*='option']:first-child",
                        "[class*='result']:first-child", "ul li:first-child"]:
                try:
                    page.click(sug, timeout=2000)
                    page.wait_for_timeout(1500)
                    break
                except Exception: pass
            break
        except Exception: pass

    # Click first branch button
    for btn_sel in ["[class*='branch']:first-child", "[class*='store']:first-child button",
                    "button:has-text('בחר')", "button:has-text('בחירה')", "a:has-text('בחר סניף')"]:
        try:
            page.click(btn_sel, timeout=3000)
            page.wait_for_timeout(2000)
            break
        except Exception: pass

    sc(page, "04_after_branch")
    print(f"  URL after branch: {page.url}")

    # ── 3. Navigate to menu / shop ────────────────────────────────────────────
    print("3. Shop/menu pages...")
    for path in ["/shop/", "/product-category/pizzas/", "/product-category/meals/", "/product-category/deals/"]:
        url = "https://www.papajohns.co.il" + path
        try:
            resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            name = path.strip("/").replace("/", "_")
            sc(page, f"05_{name}")
            status = resp.status if resp else "?"
            title  = page.title()[:50]
            lines  = visible_text_with_prices(page)
            prices = dom_prices(page)
            print(f"  {path}: HTTP {status} | {title}")
            print(f"  Text lines with numbers ({len(lines)}):")
            for l in lines[:20]:
                print(f"    {l!r}")
            print(f"  DOM prices ({len(prices)}):")
            for p in prices[:15]:
                print(f"    {p!r}")
        except Exception as e:
            print(f"  {path}: error — {str(e)[:60]}")

    # ── 4. Click into a pizza product ─────────────────────────────────────────
    print("\n4. Single product page...")
    try:
        page.goto("https://www.papajohns.co.il/shop/", timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        # Find all product links
        links = page.evaluate("""() =>
            Array.from(document.querySelectorAll('a'))
            .filter(a => /product|פיצ|shop/i.test(a.href) && a.href !== window.location.href)
            .map(a => ({href: a.href, text: (a.innerText||'').trim().slice(0,40)}))
            .slice(0, 10)
        """)
        print(f"  Product links: {links}")
        if links:
            page.goto(links[0]["href"], timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            sc(page, "06_product")
            prices = dom_prices(page)
            lines  = visible_text_with_prices(page)
            print(f"  Product page: {page.url[:80]}")
            for l in lines[:20]: print(f"    {l!r}")
    except Exception as e:
        print(f"  error: {str(e)[:80]}")

    # ── 5. Full-page screenshots of key pages ─────────────────────────────────
    print("\n5. Full-page screenshots for OCR...")
    for path, name in [("/shop/", "shop_full"), ("/product-category/pizzas/", "pizza_full")]:
        try:
            page.goto("https://www.papajohns.co.il" + path, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            p = str(OUT / f"pj_ocr_{name}.png")
            page.screenshot(path=p, full_page=True)
            print(f"  📷 {name} (full page)")
        except Exception as e:
            print(f"  {path}: {str(e)[:60]}")

    browser.close()
print("\nDone.")
