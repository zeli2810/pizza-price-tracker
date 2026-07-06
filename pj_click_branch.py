"""Click a specific branch by coordinates, then screenshot and extract all menu prices."""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "data"
UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
STEALTH = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};"

def sc(page, name, full=False):
    p = str(OUT / f"pj_click_{name}.png")
    page.screenshot(path=p, full_page=full)
    print(f"  📷 {name} ({'full' if full else 'viewport'})")
    return p

def page_text_lines(page):
    return page.evaluate("""() => {
        return (document.body?.innerText||'')
            .split('\\n').map(l=>l.trim())
            .filter(l=>l && l.length>1 && l.length<300);
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
    for sel in ["button:has-text('הבנתי')","#CybotCookiebotDialogBodyButtonAccept"]:
        try: page.click(sel,timeout=2000); break
        except: pass
    page.click("text=איסוף עצמי", timeout=5000)
    page.wait_for_timeout(3000)
    print(f"URL: {page.url}")

    # 2. Look at actual DOM structure of branch rows
    rows_info = page.evaluate("""() => {
        const rows = [];
        document.querySelectorAll('li, [class*="branch"], [class*="store"], [class*="item"]').forEach(el => {
            const t = (el.innerText||'').trim().slice(0,80);
            if (t && /[א-ת]{2}/.test(t) && el.offsetHeight > 30 && el.offsetHeight < 200) {
                const rect = el.getBoundingClientRect();
                rows.push({text: t, tag: el.tagName, className: el.className.slice(0,60),
                           x: Math.round(rect.x), y: Math.round(rect.y),
                           w: Math.round(rect.width), h: Math.round(rect.height)});
            }
        });
        return rows.slice(0,20);
    }""")
    print("Branch row elements:")
    for r in rows_info[:10]:
        print(f"  [{r['tag']} .{r['className'][:30]}] y={r['y']} h={r['h']} | {r['text'][:60]!r}")

    # 3. Click the first real branch row by coordinates
    # From screenshot: "אילת" row is around y=268, and spans full width. Click center.
    branch_row = next((r for r in rows_info if 'אילת' in r.get('text','') or r['y'] > 150), None)
    if branch_row:
        cx = branch_row['x'] + branch_row['w']//2
        cy = branch_row['y'] + branch_row['h']//2
        print(f"\nClicking branch at ({cx},{cy}): {branch_row['text'][:40]!r}")
        page.mouse.click(cx, cy)
        page.wait_for_timeout(4000)
    else:
        # Fallback: click at known coordinate of "אילת" from screenshot
        print("\nFallback: clicking (700, 268)...")
        page.mouse.click(700, 268)
        page.wait_for_timeout(4000)

    print(f"URL after branch click: {page.url}")
    sc(page, "01_after_branch_click")

    # 4. Check if we're now on a menu page
    all_lines = page_text_lines(page)
    print(f"\nPage text lines ({len(all_lines)}):")
    for l in all_lines[:30]: print(f"  {l!r}")

    # 5. Navigate to categories within the store
    print("\n\nLooking for menu categories...")
    cats = page.evaluate("""() => {
        const items = [];
        document.querySelectorAll('a, button').forEach(el => {
            const t = (el.innerText||el.textContent||'').trim();
            const h = el.href||'';
            if (t && t.length>1 && t.length<25 && /[א-ת]/.test(t)) {
                items.push({text:t, href:h.slice(0,80), tag:el.tagName});
            }
        });
        return [...new Map(items.map(c=>[c.text,c])).values()].slice(0,30);
    }""")
    print("Nav/buttons:", [c['text'] for c in cats])

    # Click through pizza-related nav items
    pizza_related = [c for c in cats if any(k in c['text'] for k in
        ['פיצ','ארוחה','ארוחות','מבצע','קומבו','תפריט','פאמיל','משפח','סט','חבילה'])]
    print("Pizza nav:", [c['text'] for c in pizza_related])

    all_price_lines = list(all_lines)

    for cat in pizza_related[:4]:
        try:
            if cat['href'] and cat['href'] not in ['','#',page.url]:
                page.goto(cat['href'], timeout=15000, wait_until="domcontentloaded")
            else:
                page.click(f"text={cat['text']}", timeout=3000)
            page.wait_for_timeout(3000)
            name = cat['text'].replace(' ','_')[:12]
            sc(page, f"02_{name}", full=True)
            lines = page_text_lines(page)
            price_lines = [l for l in lines if re.search(r'\d{2,3}', l)]
            print(f"\n  {cat['text']}: {len(price_lines)} price lines")
            for l in price_lines[:20]: print(f"    {l!r}")
            all_price_lines.extend(lines)
        except Exception as e:
            print(f"  {cat['text']}: {str(e)[:60]}")

    # 6. If still on branch list, try clicking the chevron < on row 1
    if '/shop' in page.url and len(all_price_lines) < 50:
        print("\nTrying chevron click...")
        chev = page.evaluate("""() => {
            const arrows = [];
            document.querySelectorAll('svg, [class*="chevron"], [class*="arrow"], span').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.y > 200 && rect.y < 350 && rect.x < 200) {
                    arrows.push({x:Math.round(rect.x+rect.width/2), y:Math.round(rect.y+rect.height/2),
                                 tag:el.tagName, class:el.className.slice(0,30)});
                }
            });
            return arrows;
        }""")
        print(f"Chevron-like elements at left side: {chev[:5]}")
        if chev:
            page.mouse.click(chev[0]['x'], chev[0]['y'])
            page.wait_for_timeout(3000)
            sc(page, "03_after_chevron")
            print(f"URL: {page.url}")
            lines = page_text_lines(page)
            for l in lines[:30]: print(f"  {l!r}")
            all_price_lines.extend(lines)

    # Save results
    (OUT/"pj_menu_text.json").write_text(
        json.dumps(all_price_lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nTotal lines saved: {len(all_price_lines)}")
    browser.close()
print("Done.")
