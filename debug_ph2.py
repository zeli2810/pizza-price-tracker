"""Dump full body.innerText from Pizza Hut."""
import sys, io
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
    page.goto("https://www.pizzahut.co.il", timeout=30000, wait_until="networkidle")
    page.wait_for_timeout(2000)

    body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
    print(f"Body text length: {len(body_text)}")
    print("=== First 3000 chars of body.innerText ===")
    print(body_text[:3000])

    # Also check specific elements
    price_elements = page.evaluate("""() => {
        const results = [];
        ['h1','h2','h3','p','span','div','strong','b','a'].forEach(tag => {
            document.querySelectorAll(tag).forEach(el => {
                const t = (el.innerText||el.textContent||'').trim();
                if (t && t.length < 100 && /[0-9]/.test(t) && (t.includes('₪') || t.includes('שח') || t.includes('מחיר'))) {
                    results.push({tag, text: t});
                }
            });
        });
        return results.slice(0, 30);
    }""")
    print("\n\n=== Elements with price context ===")
    for e in price_elements:
        print(f"  <{e['tag']}>: {e['text']!r}")

    b.close()
