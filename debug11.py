"""Use page.evaluate fetch() to call Domino's API with browser cookies."""
import sys, io, json, re
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

    # Let the site initialize (triggers connect, setLang, getCustomerDetails, getStoreList automatically)
    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Click through ordering flow to further initialize session
    try:
        page.click("div:has-text('תפריט והזמנה')", timeout=3000)
        page.wait_for_timeout(500)
        page.click("button:has-text('איסוף עצמי')", timeout=3000)
        page.wait_for_timeout(3000)
    except: pass

    # Now use fetch() from within the page to call API with browser cookies
    def browser_fetch(endpoint, payload):
        return page.evaluate(f"""async () => {{
            try {{
                const resp = await fetch('https://api.dominos.co.il/{endpoint}', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    credentials: 'include',
                    body: JSON.stringify({json.dumps(payload)})
                }});
                const text = await resp.text();
                return {{status: resp.status, body: text}};
            }} catch(e) {{
                return {{status: 0, body: e.toString()}};
            }}
        }}""")

    # Get store list
    print("getStoreList via browser fetch:")
    r = browser_fetch("getStoreList", {"requestNum": 10})
    print(f"  Status: {r['status']}")
    try:
        data = json.loads(r["body"])
        stores = data.get("data", [])
        print(f"  Stores: {len(stores)}")
        if stores:
            print(f"  First: {json.dumps(stores[0], ensure_ascii=False)[:150]}")
            store_id = stores[0]["id"]
        else:
            store_id = "501"
    except:
        print(f"  Raw: {r['body'][:200]}")
        store_id = "501"

    print(f"\nUsing store_id: {store_id}")

    # selectSubService
    r2 = browser_fetch("selectSubService", {"subService": "pu", "requestNum": 11})
    print(f"\nselectSubService: {r2['status']} - {r2['body'][:100]}")

    # Try store-related endpoints
    print(f"\nTrying endpoints after selectSubService...")
    for ep, payload in [
        ("getOrderingStatus", {"requestNum": 12}),
        ("selectStore", {"storeId": store_id, "requestNum": 13}),
        ("setStore", {"storeId": store_id, "requestNum": 13}),
        ("getMenuData", {"storeId": store_id, "requestNum": 14}),
        ("getMenu", {"storeId": store_id, "requestNum": 14}),
        ("getOrderFlow", {"storeId": store_id, "requestNum": 14}),
    ]:
        r = browser_fetch(ep, payload)
        try:
            d = json.loads(r["body"])
            body_str = json.dumps(d, ensure_ascii=False)
            prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body_str)
            size = len(body_str)
            st = d.get("status", "?")
            print(f"  {ep}: HTTP={r['status']} api_status={st} size={size} prices={prices[:5]}")
            if prices:
                (OUT / f"DOMINOS_{ep}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  *** PRICES FOUND! Saved DOMINOS_{ep}.json ***")
        except Exception as e:
            print(f"  {ep}: {r['status']} raw={r['body'][:100]}")

    b.close()
