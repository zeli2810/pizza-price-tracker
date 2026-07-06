import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
STEALTH = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};"

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
                            args=["--disable-blink-features=AutomationControlled","--no-sandbox"])
    ctx = br.new_context(locale="he-IL", timezone_id="Asia/Jerusalem",
                         viewport={"width":1440,"height":900}, user_agent=UA)
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()
    page.goto("https://www.papajohns.co.il/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    try: page.click("text=הבנתי", timeout=2000)
    except: pass
    page.click("text=איסוף עצמי", timeout=8000)
    page.wait_for_timeout(3000)

    count = page.locator("text=לחץ על מנת להתחיל הזמנה").count()
    print(f"Branch buttons count: {count}")

    lines = page.evaluate("() => (document.body.innerText || '').split('\\n').map(l=>l.trim()).filter(l=>l)")
    for i, l in enumerate(lines):
        if "לחץ על מנת" in l:
            ctx_lines = lines[max(0,i-3):i+1]
            print(f"Button: context = {ctx_lines}")

    # Click nth=1 (second branch = אשדוד)
    page.locator("text=לחץ על מנת להתחיל הזמנה").nth(1).click(timeout=8000)
    page.wait_for_timeout(5000)
    print(f"URL after: {page.url}")

    lines2 = page.evaluate("() => (document.body.innerText || '').split('\\n').map(l=>l.trim()).filter(l=>l && l.length<300)")
    branch_confirm = [l for l in lines2 if any(k in l for k in ["איסוף מסניף","אשדוד","אילת","סניף"])]
    print(f"Branch confirmation: {branch_confirm[:5]}")

    br.close()
print("Done.")
