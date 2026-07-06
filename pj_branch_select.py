"""
Click a branch, wait for the menu to load, take full-page screenshots of all categories.
"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "data"
UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
"""

def sc(page, name, full=False):
    p = str(OUT / f"pj_menu_{name}.png")
    page.screenshot(path=p, full_page=full)
    print(f"  📷 {name}")
    return p

def get_text_prices(page):
    return page.evaluate("""() => {
        const lines = (document.body?.innerText || '').split('\\n')
            .map(l => l.trim())
            .filter(l => l && /\\d/.test(l) && l.length > 1 && l.length < 200);
        return [...new Set(lines)];
    }""")

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        channel="chrome", headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    ctx = browser.new_context(locale="he-IL", timezone_id="Asia/Jerusalem",
                              viewport={"width": 1440, "height": 900}, user_agent=UA)
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()

    # ── 1. Go to homepage, pick pickup ───────────────────────────────────────
    print("1. Homepage → איסוף עצמי...")
    page.goto("https://www.papajohns.co.il/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    # Cookie
    for sel in ["button:has-text('הבנתי')", "#CybotCookiebotDialogBodyButtonAccept"]:
        try: page.click(sel, timeout=2000); break
        except: pass
    # Pick pickup
    page.click("text=איסוף עצמי", timeout=5000)
    page.wait_for_timeout(3000)
    print(f"  URL: {page.url}")

    # ── 2. Click first branch ─────────────────────────────────────────────────
    print("2. Clicking first branch...")
    sc(page, "00_branch_list")
    # The branch rows have a chevron <  on the left side. Click the first branch row.
    branch_clicked = False
    for sel in [
        "li:first-child",
        "[class*='branch']:first-child",
        "[class*='store']:first-child",
        "ul li:first-child",
        ".branch-item:first-child",
        # Try clicking a row by its Hebrew text (first in alphabetical list = אילת)
        "text=אילת",
        # Try any clickable row
        "li:has(svg)",  # rows with location pin SVG
    ]:
        try:
            page.click(sel, timeout=3000)
            page.wait_for_timeout(2500)
            branch_clicked = True
            print(f"  Clicked branch: {sel}")
            print(f"  URL after: {page.url}")
            break
        except: pass

    if not branch_clicked:
        # Try JavaScript click on first row
        clicked = page.evaluate("""() => {
            const rows = document.querySelectorAll('li, [role=listitem], [class*=branch], [class*=store]');
            for (const row of rows) {
                if (row.innerText && row.innerText.trim().length > 2 && /[א-ת]/.test(row.innerText)) {
                    row.click(); return row.innerText.trim().slice(0,40);
                }
            }
            return null;
        }""")
        page.wait_for_timeout(2500)
        print(f"  JS click: {clicked}, URL: {page.url}")

    sc(page, "01_after_branch")

    # ── 3. Wait for menu to fully render ─────────────────────────────────────
    print("3. Waiting for menu to load...")
    # Wait for any product/category elements
    try:
        page.wait_for_selector("[class*='product'], [class*='item'], [class*='category'], [class*='pizza']", timeout=10000)
    except:
        pass
    page.wait_for_timeout(3000)
    print(f"  Final URL: {page.url}")
    sc(page, "02_menu_loaded", full=True)

    # Get all text from page
    lines = get_text_prices(page)
    print(f"\n  All text lines with numbers ({len(lines)}):")
    for l in lines[:40]:
        print(f"    {l!r}")

    # ── 4. Click through menu categories ─────────────────────────────────────
    print("\n4. Clicking through menu categories...")
    categories = page.evaluate("""() => {
        const cats = [];
        document.querySelectorAll('nav a, [class*="menu"] a, [class*="nav"] a, [class*="category"] a, [class*="tab"] a, button').forEach(el => {
            const t = (el.innerText||el.textContent||'').trim();
            if (t && t.length < 30 && /[א-ת]/.test(t)) {
                cats.push({text: t, href: el.href||'', tag: el.tagName});
            }
        });
        return [...new Map(cats.map(c=>[c.text,c])).values()].slice(0,20);
    }""")
    print(f"  Nav items: {[c['text'] for c in categories]}")

    # Click each pizza-related category
    pizza_cats = [c for c in categories if any(k in c['text'] for k in ['פיצ', 'ארוחה', 'מבצע', 'תפריט', 'קומבו', 'סט'])]
    print(f"  Pizza categories: {[c['text'] for c in pizza_cats]}")

    all_prices_raw = list(lines)

    for cat in pizza_cats[:5]:
        try:
            if cat['href'] and cat['href'] not in [page.url, '#']:
                page.goto(cat['href'], timeout=15000, wait_until="domcontentloaded")
            else:
                page.click(f"text={cat['text']}", timeout=3000)
            page.wait_for_timeout(3000)
            name = cat['text'].replace(' ', '_').replace("'", '')[:15]
            sc(page, f"03_{name}", full=True)
            new_lines = get_text_prices(page)
            print(f"  {cat['text']}: {len(new_lines)} text lines")
            for l in new_lines[:15]: print(f"    {l!r}")
            all_prices_raw.extend(new_lines)
        except Exception as e:
            print(f"  {cat['text']}: error — {str(e)[:60]}")

    # ── 5. Click first product to see variant prices ──────────────────────────
    print("\n5. Opening first product...")
    try:
        page.goto("https://www.papajohns.co.il/shop/", timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        # Find clickable product items
        prods = page.evaluate("""() => {
            const items = [];
            document.querySelectorAll('[class*="product"], [class*="item"], [class*="card"]').forEach(el => {
                if (el.offsetWidth > 50 && el.offsetHeight > 50) {
                    const name = (el.querySelector('h2,h3,h4,[class*="title"],[class*="name"]')?.innerText||'').trim();
                    if (name && /[א-ת]/.test(name)) items.push({name: name.slice(0,40), rect: {x: el.getBoundingClientRect().x, y: el.getBoundingClientRect().y}});
                }
            });
            return items.slice(0,5);
        }""")
        print(f"  Products found: {prods}")
        if prods:
            # Click the first product
            r = prods[0]['rect']
            page.mouse.click(r['x'] + 10, r['y'] + 10)
            page.wait_for_timeout(3000)
            sc(page, "04_product_dialog", full=False)
            new_lines = get_text_prices(page)
            print(f"  Product dialog text:")
            for l in new_lines[:20]: print(f"    {l!r}")
            all_prices_raw.extend(new_lines)
    except Exception as e:
        print(f"  error: {str(e)[:80]}")

    # Save raw lines
    (OUT / "pj_raw_text.json").write_text(
        json.dumps(all_prices_raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nTotal raw lines: {len(all_prices_raw)}")
    browser.close()
print("Done.")
