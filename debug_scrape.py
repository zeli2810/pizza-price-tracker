"""Debug script - saves screenshots and page text to understand site structure."""
import sys, io, os
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"

def dump_site(pw, name, url):
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        locale="he-IL",
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = ctx.new_page()
    print(f"\n=== {name} ===")
    try:
        page.goto(url, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)
        title = page.title()
        print(f"Title: {title}")
        print(f"URL: {page.url}")

        # Save screenshot
        ss_path = OUT / f"debug_{name}.png"
        page.screenshot(path=str(ss_path), full_page=False)
        print(f"Screenshot: {ss_path}")

        # Get all text with shekel sign
        items = page.evaluate("""() => {
            const seen = new Set();
            const out = [];
            document.querySelectorAll('*').forEach(el => {
                const t = (el.innerText || '').trim();
                if (t && t.length < 300 && !seen.has(t)) {
                    if (t.includes('₪') || t.includes('שח') || t.includes('ש"ח')) {
                        seen.add(t);
                        out.push(t);
                    }
                }
            });
            return out.slice(0, 50);
        }""")
        print(f"Price texts found: {len(items)}")
        for i in items[:20]:
            print(f"  {i}")

        # Also get all links
        links = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href + ' | ' + (a.innerText||'').trim().slice(0,40))
                .filter(s => s.length > 5)
                .slice(0, 30);
        }""")
        print(f"Links:")
        for l in links[:15]:
            print(f"  {l}")

    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        browser.close()

with sync_playwright() as pw:
    dump_site(pw, "dominos", "https://www.dominos.co.il")
    dump_site(pw, "pizzahut", "https://www.pizzahut.co.il")
    dump_site(pw, "papajohns", "https://www.papajohnspizza.co.il")
