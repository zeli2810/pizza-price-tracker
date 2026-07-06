"""Debug Domino's - find the skip link and menu prices."""
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    # ── Step 1: homepage ──
    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # ── Step 2: click תפריט והזמנה first ──
    try:
        page.click("div:has-text('תפריט והזמנה')", timeout=4000)
        page.wait_for_timeout(1500)
        print("Clicked 'תפריט והזמנה'")
    except Exception as e:
        print("Could not click תפריט והזמנה:", e)

    # ── Step 3: click איסוף עצמי ──
    try:
        page.click("button:has-text('איסוף עצמי')", timeout=4000)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "dom_after_aisuf.png"))
        print("Clicked 'איסוף עצמי'")
    except Exception as e:
        print("Could not click איסוף עצמי:", e)

    # ── Step 4: try get_by_text to find the skip link ──
    print("\nLooking for skip link...")
    all_links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a, button, [role=button], span[onclick]'))
            .map(el => (el.innerText||el.textContent||'').trim().slice(0,100))
            .filter(t => t.length > 0)
    }""")
    for t in all_links:
        if "ראות" in t or "ראה" in t or "רק" in t or "דלג" in t or "המשך" in t:
            print(f"  FOUND: {repr(t)}")

    # ── Step 5: try clicking the skip link ──
    clicked_skip = False
    try:
        page.get_by_text("אני רק רוצה לראות", exact=False).click(timeout=3000)
        page.wait_for_timeout(2500)
        clicked_skip = True
        print("Clicked skip link via get_by_text")
    except Exception as e:
        print("get_by_text failed:", e)

    if not clicked_skip:
        # Try with locator
        try:
            page.locator("text=אני רק").click(timeout=3000)
            page.wait_for_timeout(2500)
            clicked_skip = True
            print("Clicked via locator text=")
        except Exception as e2:
            print("locator failed:", e2)

    page.screenshot(path=str(OUT / "dom_after_skip.png"))
    print("URL after skip:", page.url)

    # ── Step 6: try direct branch URL ──
    print("\nTrying branch URL directly...")
    page.goto("https://www.dominos.co.il/branches/Tel-Aviv-City", timeout=20000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "dom_branch_page.png"))
    print("Branch page URL:", page.url)
    print("Branch page title:", page.title())

    # Check for prices
    items = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText||'').trim();
            if (t && t.length < 300 && !seen.has(t) && t.includes('₪')) {
                seen.add(t); out.push(t);
            }
        });
        return out.slice(0, 30);
    }""")
    print(f"Price texts on branch page: {len(items)}")
    for i in items[:15]: print(f"  {i!r}")

    # ── Step 7: try content/Family-Pizza page ──
    print("\nTrying family pizza content page...")
    page.goto("https://www.dominos.co.il/content/Family-Pizza", timeout=20000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "dom_family_page.png"))
    print("Family page URL:", page.url)

    items2 = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText||'').trim();
            if (t && t.length < 400 && !seen.has(t) && /[0-9]/.test(t)) {
                seen.add(t); out.push(t);
            }
        });
        return out.slice(0, 40);
    }""")
    print(f"All numeric texts on family page: {len(items2)}")
    for i in items2[:20]: print(f"  {i!r}")

    b.close()
