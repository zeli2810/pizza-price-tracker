"""Deep debug - find where prices actually live on each site."""
import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def check(pw, name, steps):
    """steps = list of (action, value) tuples"""
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()
    try:
        for action, val in steps:
            if action == "goto":
                page.goto(val, timeout=25000, wait_until="networkidle")
                page.wait_for_timeout(3000)
            elif action == "click_text":
                try:
                    page.get_by_text(val, exact=False).first.click(timeout=3000)
                    page.wait_for_timeout(2000)
                except: pass
            elif action == "click_sel":
                try:
                    page.click(val, timeout=3000)
                    page.wait_for_timeout(2000)
                except: pass
            elif action == "wait":
                page.wait_for_timeout(val)

        print(f"\n=== {name} ===")
        print(f"URL: {page.url}")
        print(f"Title: {page.title()}")

        # Screenshot
        page.screenshot(path=str(OUT / f"debug2_{name}.png"))

        # All text with numbers
        items = page.evaluate("""() => {
            const seen = new Set();
            const out = [];
            document.querySelectorAll('*').forEach(el => {
                const t = (el.innerText || '').trim();
                if (t && t.length < 200 && !seen.has(t) && /\d/.test(t)) {
                    seen.add(t);
                    out.push(t);
                }
            });
            return out.slice(0, 60);
        }""")
        print(f"Text nodes with numbers ({len(items)}):")
        for i in items[:30]:
            print(f"  {repr(i)}")

    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        b.close()

with sync_playwright() as pw:
    # Domino's - try clicking pickup then first branch
    check(pw, "dominos_pickup", [
        ("goto", "https://www.dominos.co.il"),
        ("click_text", "איסוף"),
        ("wait", 2000),
        ("click_sel", "li:first-child, .branch:first-child, .store:first-child"),
        ("wait", 2000),
    ])

    # Pizza Hut - dismiss cookie then click order
    check(pw, "pizzahut_order", [
        ("goto", "https://www.pizzahut.co.il"),
        ("click_sel", "#CybotCookiebotDialogBodyButtonAccept"),
        ("wait", 1000),
        ("click_text", "להזמנה"),
        ("wait", 3000),
    ])

    # Papa John's - try alternative URLs
    check(pw, "papajohns_v1", [
        ("goto", "https://www.papajohns.co.il"),
    ])

    check(pw, "papajohns_v2", [
        ("goto", "https://papajohns.co.il"),
    ])
