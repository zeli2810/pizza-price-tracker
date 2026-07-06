import sys, io, re, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup
from pathlib import Path

BASE = Path(__file__).parent / "data"
UA   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

# ── 1. Wayback Machine snapshot ───────────────────────────────────────────────
print("=== Wayback Machine ===")
try:
    api = requests.get("https://archive.org/wayback/available?url=papajohns.co.il/shop/", timeout=10).json()
    snap = api.get("archived_snapshots", {}).get("closest", {})
    print(f"  available: {snap.get('available')}, ts: {snap.get('timestamp')}, url: {snap.get('url','')[:80]}")
    if snap.get("available"):
        r = requests.get(snap["url"], headers={"User-Agent": UA}, timeout=20)
        print(f"  fetch: {r.status_code} ({len(r.text)}b)")
        if r.status_code == 200:
            (BASE / "pj_wayback.html").write_text(r.text, encoding="utf-8")
            print("  Saved pj_wayback.html")
except Exception as e:
    print(f"  error: {e}")

# ── 2. Check pj_cache.html content (what did google cache return?) ─────────────
print()
print("=== Google Cache content preview ===")
cache_file = BASE / "pj_cache.html"
if cache_file.exists():
    html = cache_file.read_text(encoding="utf-8", errors="replace")
    # Find all links to Papa John's cached pages
    soup = BeautifulSoup(html, "html.parser")
    print(f"  Page title: {soup.title.get_text()[:100] if soup.title else 'none'}")
    # Find any links to the actual cached page
    for a in soup.find_all("a", href=True)[:10]:
        href = a["href"]
        if "papajohns" in href.lower() or "cache" in href.lower():
            print(f"  Link: {href[:100]}")

# ── 3. Try Playwright with real Chrome (channel="chrome") ─────────────────────
print()
print("=== Playwright with Chrome channel ===")
try:
    from playwright.sync_api import sync_playwright
    STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['he-IL', 'he', 'en-US']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
"""
    with sync_playwright() as pw:
        # Try Chrome channel
        for channel in ["chrome", "msedge", None]:
            try:
                kwargs = {"headless": True, "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"]}
                if channel:
                    kwargs["channel"] = channel
                browser = pw.chromium.launch(**kwargs)
                ctx = browser.new_context(
                    locale="he-IL", timezone_id="Asia/Jerusalem",
                    viewport={"width": 1440, "height": 900},
                    user_agent=UA,
                )
                ctx.add_init_script(STEALTH)
                page = ctx.new_page()

                for url in ["https://www.papajohns.co.il/", "https://www.papajohns.co.il/shop/"]:
                    try:
                        resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
                        page.wait_for_timeout(4000)
                        sc = str(BASE / f"pj_chrome_{(channel or 'chromium').replace(' ','_')}.png")
                        page.screenshot(path=sc, full_page=False)
                        status = resp.status if resp else "?"
                        title = page.title()
                        content_len = len(page.content())
                        print(f"  [{channel or 'chromium'}] {url}: {status} | {title[:40]} | {content_len}b")
                        if status == 200 and content_len > 5000 and "Access Denied" not in title:
                            html = page.content()
                            (BASE / f"pj_{channel or 'chromium'}.html").write_text(html, encoding="utf-8")
                            print(f"  ✓ Got page! Saved.")
                    except Exception as e:
                        print(f"  [{channel or 'chromium'}] {url}: {str(e)[:60]}")
                browser.close()
                break
            except Exception as e:
                print(f"  channel={channel} launch failed: {str(e)[:80]}")
                continue
except Exception as e:
    print(f"  Playwright error: {e}")

# ── 4. Parse Wayback HTML if we got it ────────────────────────────────────────
wb = BASE / "pj_wayback.html"
if wb.exists():
    print()
    print("=== Parsing Wayback HTML ===")
    html = wb.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    print(f"Title: {soup.title.get_text()[:80] if soup.title else 'none'}")

    # Remove Wayback toolbar
    for sel in [".wb-autocomplete-suggestions", "#wm-ipp", "#wm-ipp-base"]:
        for el in soup.select(sel): el.decompose()

    # Products
    products = []
    for prod in soup.select("li.product, .product-card, article.product, .product-item"):
        name  = prod.select_one(".woocommerce-loop-product__title, h2, h3, .product-title, .entry-title")
        price = prod.select_one(".woocommerce-Price-amount, .price .amount, bdi")
        if name or price:
            n = name.get_text(" ", strip=True)[:80] if name else ""
            p = price.get_text(" ", strip=True)[:20] if price else ""
            products.append((n, p))
            print(f"  Product: {n!r:50} | price: {p!r}")

    # ₪ prices
    print()
    for el in soup.find_all(string=re.compile(r"₪")):
        t = el.strip()
        if t:
            ctx = el.find_parent().get_text(" ", strip=True)[:100] if el.find_parent() else ""
            print(f"  ₪ hit: {t!r:20} | {ctx[:80]!r}")

    # JSON-LD
    for script in soup.select("script[type='application/ld+json']"):
        try:
            d = json.loads(script.string or "")
            s = json.dumps(d, ensure_ascii=False)
            if "price" in s.lower() or "pizza" in s.lower():
                print(f"  LD+JSON: {s[:300]}")
        except Exception:
            pass
