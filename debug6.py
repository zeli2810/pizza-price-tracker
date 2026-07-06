"""Navigate Domino's full ordering flow and capture menu API with prices."""
import sys, io, json, re
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

api_responses = {}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    def on_response(resp):
        url = resp.url
        if "api.dominos.co.il" in url or "cdn.dominos.co.il/assets" in url:
            try:
                body = resp.text()
                if url not in api_responses:
                    api_responses[url] = body
                    prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
                    flag = f" *** PRICES: {prices[:5]}" if prices else ""
                    print(f"  [{len(body)}b] {url.split('/')[-1].split('?')[0][:50]}{flag}")
            except Exception:
                pass

    page.on("response", on_response)

    # Load homepage
    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Click תפריט והזמנה
    try:
        page.click("div:has-text('תפריט והזמנה')", timeout=3000)
        page.wait_for_timeout(800)
    except: pass

    # Click איסוף עצמי
    try:
        page.click("button:has-text('איסוף עצמי')", timeout=3000)
        page.wait_for_timeout(3000)
    except: pass

    page.screenshot(path=str(OUT / "dom6_step1.png"))

    # Now we should see the branch selection. Look for any store/branch buttons
    branch_items = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('li, [role=option], .store-item, .branch-item, button'))
            .map(el => ({text: (el.innerText||'').trim().slice(0,60), tag: el.tagName}))
            .filter(x => x.text.length > 2 && x.text.length < 50)
            .slice(0, 50);
    }""")
    print("\nPossible branch items:")
    for i in branch_items[:20]:
        print(f"  [{i['tag']}] {i['text']!r}")

    # Try clicking the first branch-like item after the skip
    try:
        page.get_by_text("אני רק רוצה", exact=False).click(timeout=3000)
        page.wait_for_timeout(2000)
        print("Clicked skip link")
    except Exception as e:
        print(f"Skip link: {e}")

    # Now find branch selector on the resulting page
    page.screenshot(path=str(OUT / "dom6_step2.png"))
    print("\nURL after skip:", page.url)

    # Try navigating to a specific store's menu
    # Store 501 = אבן גבירול תל אביב
    page.goto("https://www.dominos.co.il/order/store/501", timeout=20000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "dom6_store501.png"))
    print("\nStore 501 URL:", page.url)
    print("Store 501 title:", page.title())

    # Check for prices
    texts = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText||'').trim();
            if (t && t.length < 200 && !seen.has(t) && /[₪\d]/.test(t)) {
                seen.add(t); out.push(t);
            }
        });
        return out.slice(0, 30);
    }""")
    print(f"\nTexts with prices/numbers ({len(texts)}):")
    for t in texts[:20]: print(f"  {t!r}")

    print("\n\n=== ALL API CALLS with prices ===")
    for url, body in api_responses.items():
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
        if prices:
            print(f"\n{url}")
            print(f"Prices: {prices[:20]}")
            try:
                data = json.loads(body)
                (OUT / f"PRICES_{url.split('/')[-1].split('?')[0][:40]}.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except: pass

    b.close()
