"""Navigate Papa John's full ordering flow using Chrome channel and extract pizza prices."""
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

def pick_price(text):
    if not text: return None
    for m in re.findall(r"[\d]+(?:[.,]\d{1,2})?", str(text).replace(",", "")):
        v = float(m.replace(",", "."))
        if 20 < v < 800:
            return v
    return None

def screenshot(page, name):
    path = str(OUT / f"pj_nav_{name}.png")
    page.screenshot(path=path, full_page=False)
    print(f"  📷 {name}.png")
    return path

def get_all_prices(page):
    """Extract all (name, price) pairs visible on page."""
    return page.evaluate("""() => {
        const items = [];
        const seen  = new Set();
        // WooCommerce product cards
        document.querySelectorAll('li.product, .product-card, article.product, .wc-block-grid__product').forEach(el => {
            const name  = el.querySelector('.woocommerce-loop-product__title, h2, h3, .product-title, .wc-block-grid__product-title');
            const price = el.querySelector('bdi, .price .amount, .woocommerce-Price-amount');
            const n = (name?.innerText||'').trim().slice(0,80);
            const p = (price?.innerText||'').trim().slice(0,30);
            const key = n+'|'+p;
            if ((n||p) && !seen.has(key)) { seen.add(key); items.push({name:n, price:p, src:'woo'}); }
        });
        // Any element with ₪
        document.querySelectorAll('*').forEach(el => {
            const t = (el.childNodes[0]?.nodeValue||'').trim();
            if (t && t.includes('₪') && t.length < 50 && !seen.has(t)) {
                seen.add(t);
                const ctx = (el.closest('[class]')?.innerText||'').trim().slice(0,100);
                items.push({name: ctx, price: t, src:'shekel'});
            }
        });
        // Price spans / bdi
        document.querySelectorAll('bdi, .price').forEach(el => {
            const t = el.innerText?.trim();
            if (t && /\\d{2,3}/.test(t) && !seen.has(t)) {
                seen.add(t);
                const ctx = el.closest('li, article, .product, section')?.querySelector('h2,h3,h4,.title')?.innerText?.trim()||'';
                items.push({name: ctx.slice(0,80), price: t.slice(0,30), src:'bdi'});
            }
        });
        return items;
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

    # ── Step 1: Homepage ──────────────────────────────────────────────────────
    print("Step 1: Homepage...")
    page.goto("https://www.papajohns.co.il/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    screenshot(page, "01_home")

    # Click "איסוף עצמי" (pickup - simpler, no address needed)
    print("  Clicking 'איסוף עצמי'...")
    clicked = False
    for sel in ["text=איסוף עצמי", "button:has-text('איסוף')", "a:has-text('איסוף')"]:
        try:
            page.click(sel, timeout=4000)
            page.wait_for_timeout(2000)
            clicked = True
            print(f"  ✓ clicked '{sel}'")
            break
        except Exception:
            pass

    if not clicked:
        # Try clicking any button
        buttons = page.evaluate("() => Array.from(document.querySelectorAll('button,a')).map(el=>({text:el.innerText?.trim()?.slice(0,40),href:el.href||''}))")
        print("  Available buttons/links:", buttons[:10])
        # Navigate directly to shop
        page.goto("https://www.papajohns.co.il/shop/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

    screenshot(page, "02_after_click")

    # ── Step 2: Navigate to /shop/ ────────────────────────────────────────────
    print("\nStep 2: Navigate to /shop/...")
    page.goto("https://www.papajohns.co.il/shop/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    screenshot(page, "03_shop")
    print(f"  URL: {page.url}, title: {page.title()[:50]}")

    # Dismiss cookie popup
    for sel in ["button:has-text('הבנתי')", "button:has-text('קבלה')", "button:has-text('אישור')", "#CybotCookiebotDialogBodyButtonAccept", "button:has-text('סגור')"]:
        try:
            page.click(sel, timeout=2000)
            page.wait_for_timeout(500)
            print(f"  Dismissed: {sel}")
            break
        except Exception:
            pass

    prices_shop = get_all_prices(page)
    print(f"  Prices found on /shop/: {len(prices_shop)}")
    for p in prices_shop[:20]:
        print(f"    {p['name']!r:50} | {p['price']!r}")

    # ── Step 3: Navigate to pizza category ────────────────────────────────────
    print("\nStep 3: Pizza category pages...")
    pizza_urls = [
        "https://www.papajohns.co.il/product-category/pizzas/",
        "https://www.papajohns.co.il/product-category/pizzas/family/",
        "https://www.papajohns.co.il/product-category/meals/",
        "https://www.papajohns.co.il/product-category/deals/",
    ]
    all_prices = list(prices_shop)

    for url in pizza_urls:
        try:
            resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            name = url.split("/")[-2]
            screenshot(page, f"04_{name}")
            if resp and resp.status == 200:
                ps = get_all_prices(page)
                print(f"  {url}: {len(ps)} prices")
                for p in ps[:15]:
                    print(f"    {p['name']!r:50} | {p['price']!r}")
                all_prices.extend(ps)
        except Exception as e:
            print(f"  {url}: error — {str(e)[:60]}")

    # ── Step 4: Click on a pizza product to see variants ──────────────────────
    print("\nStep 4: Click individual pizza for size pricing...")
    try:
        page.goto("https://www.papajohns.co.il/shop/", timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.click("li.product:first-child a, .product-card:first-child a, article.product:first-child a", timeout=5000)
        page.wait_for_timeout(3000)
        screenshot(page, "05_product_detail")
        print(f"  Product page: {page.url[:80]}")
        ps = get_all_prices(page)
        print(f"  Prices: {len(ps)}")
        for p in ps[:15]:
            print(f"    {p['name']!r:50} | {p['price']!r}")
        all_prices.extend(ps)
    except Exception as e:
        print(f"  error: {str(e)[:80]}")

    # Save all found prices
    (OUT / "pj_all_prices.json").write_text(
        json.dumps(all_prices, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nTotal price records: {len(all_prices)}")
    browser.close()
