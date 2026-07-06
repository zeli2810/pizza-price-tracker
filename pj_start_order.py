"""Click 'לחץ על מנת להתחיל הזמנה' to select first branch, then extract menu prices."""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "data"
UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
STEALTH = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};"

def sc(page, name, full=False):
    p = str(OUT / f"pj_so_{name}.png")
    page.screenshot(path=p, full_page=full)
    print(f"  📷 {name}")

def all_text_lines(page):
    return page.evaluate("""() =>
        (document.body?.innerText||'').split('\\n')
        .map(l=>l.trim()).filter(l=>l && l.length>1 && l.length<300)
    """)

def price_data(page):
    return page.evaluate("""() => {
        const out = [];
        const seen = new Set();
        document.querySelectorAll('*').forEach(el => {
            if (el.children.length > 5) return;
            const t = (el.innerText||'').trim();
            if (!t || t.length > 200 || seen.has(t)) return;
            if (/[₪]/.test(t) || (t.length<100 && /\\d{2,3}/.test(t) && /[א-ת]/.test(t))) {
                seen.add(t);
                out.push(t);
            }
        });
        return out;
    }""")

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        channel="chrome", headless=True,
        args=["--disable-blink-features=AutomationControlled","--no-sandbox"]
    )
    ctx = browser.new_context(locale="he-IL", timezone_id="Asia/Jerusalem",
                              viewport={"width":1440,"height":900}, user_agent=UA)
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()

    # 1. Homepage → pickup
    page.goto("https://www.papajohns.co.il/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Click "הבנתי" (cookie consent)
    try:
        page.click("text=הבנתי", timeout=3000)
        page.wait_for_timeout(500)
        print("Dismissed cookie banner")
    except: pass

    page.click("text=איסוף עצמי", timeout=5000)
    page.wait_for_timeout(3000)
    print(f"Branch list URL: {page.url}")

    # 2. Dismiss cookie popup if it appeared
    for sel in ["text=הבנתי", "text=אפשר בחירה", "text=לדחות", "#CybotCookiebotDialogBodyButtonAccept"]:
        try:
            page.click(sel, timeout=1500)
            page.wait_for_timeout(300)
            print(f"Dismissed: {sel}")
            break
        except: pass

    sc(page, "00_branch_list")

    # 3. Click "לחץ על מנת להתחיל הזמנה" for the first branch (אילת)
    print("\nClicking 'לחץ על מנת להתחיל הזמנה'...")
    try:
        page.click("text=לחץ על מנת להתחיל הזמנה", timeout=5000)
        page.wait_for_timeout(5000)
        print(f"URL after: {page.url}")
        sc(page, "01_after_order_start")
    except Exception as e:
        print(f"Error: {e}")
        # Try JS click
        result = page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('*'));
            for (const el of els) {
                if ((el.innerText||'').trim() === 'לחץ על מנת להתחיל הזמנה') {
                    el.click(); return el.tagName + '.' + el.className.slice(0,40);
                }
            }
            return null;
        }""")
        page.wait_for_timeout(5000)
        print(f"JS click result: {result}, URL: {page.url}")
        sc(page, "01_after_js_click")

    # 4. Read page content
    lines = all_text_lines(page)
    print(f"\nPage lines ({len(lines)}):")
    for l in lines[:40]: print(f"  {l!r}")

    # 5. Look for category navigation
    cats = page.evaluate("""() => {
        const items = [];
        document.querySelectorAll('a, button, [class*="tab"], [class*="cat"]').forEach(el => {
            const t = (el.innerText||'').trim();
            const h = el.href||'';
            if (t && t.length>1 && t.length<30 && /[א-ת]/.test(t)) {
                items.push({text:t, href:h.slice(0,80), tag:el.tagName, cls:el.className.slice(0,30)});
            }
        });
        return [...new Map(items.map(c=>[c.text,c])).values()].slice(0,30);
    }""")
    print(f"\nNav items: {[c['text'] for c in cats]}")

    pizza_cats = [c for c in cats if any(k in c['text'] for k in
        ['פיצ','ארוחה','מבצע','קומבו','סט','ג\'ונס','ג׳ונס','משפח','פאמיל','חבילה','ספשל','פיית'])]
    print(f"Pizza cats: {[c['text'] for c in pizza_cats]}")

    all_lines = list(lines)

    # 6. Click each pizza category and screenshot
    for cat in pizza_cats[:5]:
        try:
            if cat['href'] and cat['href'] not in ['','#',page.url]:
                page.goto(cat['href'], timeout=15000, wait_until="domcontentloaded")
            else:
                page.click(f"text={cat['text']}", timeout=3000)
            page.wait_for_timeout(3000)
            name = cat['text'].replace(' ','_')[:12]
            sc(page, f"02_{name}", full=True)
            new_lines = all_text_lines(page)
            price_lines = [l for l in new_lines if re.search(r'\d{2,3}', l)]
            print(f"\n  {cat['text']}: {len(price_lines)} price lines")
            for l in price_lines[:20]: print(f"    {l!r}")
            all_lines.extend(new_lines)
        except Exception as e:
            print(f"  {cat['text']}: {str(e)[:60]}")

    # 7. Full-page screenshot for OCR regardless
    sc(page, "03_final_full", full=True)

    # 8. Extract structured price data
    prices = price_data(page)
    print(f"\nPrice-like elements ({len(prices)}):")
    for p in prices[:30]: print(f"  {p!r}")

    (OUT/"pj_so_text.json").write_text(
        json.dumps({"lines": all_lines, "prices": prices}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\nSaved. Total lines: {len(all_lines)}")
    browser.close()
print("Done.")
