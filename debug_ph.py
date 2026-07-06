"""Quick Pizza Hut debug."""
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA,
                        extra_http_headers={"Accept-Language": "he-IL,he;q=0.9"})
    page = ctx.new_page()
    page.goto("https://www.pizzahut.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT / "ph_before_cookie.png"))

    # Try to dismiss cookiebot
    try:
        page.click("#CybotCookiebotDialogBodyButtonAccept", timeout=5000)
        page.wait_for_timeout(2000)
        print("Dismissed cookiebot")
    except Exception as e:
        print(f"No cookiebot: {e}")

    page.screenshot(path=str(OUT / "ph_after_cookie.png"))
    page.wait_for_timeout(2000)

    # Get ALL text nodes with numbers
    texts = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText || '').trim();
            if (t && t.length < 300 && !seen.has(t) && /[0-9]/.test(t)) {
                seen.add(t); out.push(t);
            }
        });
        return out.slice(0, 50);
    }""")
    print(f"\nAll numeric texts ({len(texts)}):")
    for t in texts[:30]: print(f"  {repr(t)[:120]}")

    b.close()
