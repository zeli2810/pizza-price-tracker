"""Follow Pizza Hut's order link to find actual menu prices."""
import sys, io, re
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    # ── Step 1: click "להזמנה" and see where it goes ──
    page.goto("https://www.pizzahut.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    try:
        page.click("a:has-text('להזמנה')", timeout=4000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print(f"Could not click להזמנה: {e}")

    page.screenshot(path=str(OUT / "ph3_order.png"))
    print(f"After clicking להזמנה: {page.url}")
    print(f"Title: {page.title()}")

    # Check for prices
    body = page.evaluate("() => document.body ? document.body.innerText : ''")
    prices_in_body = re.findall(r'\d+', body)
    numeric_lines = [l.strip() for l in body.split('\n') if re.search(r'\d{2,3}', l) and len(l.strip()) < 200]
    print(f"\nNumeric lines ({len(numeric_lines)}):")
    for l in numeric_lines[:30]: print(f"  {l!r}")

    # ── Step 2: Try direct order page URLs ──
    print("\n\n=== Testing order URLs ===")
    for url in [
        "https://www.pizzahut.co.il/order",
        "https://order.pizzahut.co.il",
        "https://www.pizzahut.co.il/he/order",
        "https://online.pizzahut.co.il",
    ]:
        try:
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            page.screenshot(path=str(OUT / f"ph3_{url.split('/')[-1]}.png"))
            body2 = page.evaluate("() => document.body ? document.body.innerText.slice(0,500) : ''")
            price_lines = [l.strip() for l in body2.split('\n') if re.search(r'\d{2,3}', l) and len(l.strip()) < 100]
            print(f"\n{url}: {page.url}")
            print(f"  Title: {page.title()}")
            print(f"  Price lines: {price_lines[:5]}")
        except Exception as e:
            print(f"\n{url}: ERROR {e}")

    b.close()
