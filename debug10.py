"""Use Playwright's in-browser API calls to get Domino's menu prices."""
import sys, io, json, re
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

req_num = [1]

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    # Capture responses with prices
    api_menu_responses = {}
    def on_resp(resp):
        if "api.dominos.co.il" in resp.url and resp.url not in api_menu_responses:
            try:
                body = resp.text()
                prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body)
                size = len(body)
                if prices or size > 5000:
                    api_menu_responses[resp.url] = body
                    print(f"  API [{size}b]: {resp.url.split('/')[-1]} prices={prices[:5]}")
            except: pass

    page.on("response", on_resp)

    # Load site
    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    # Click ordering flow
    try:
        page.click("div:has-text('תפריט והזמנה')", timeout=3000)
        page.wait_for_timeout(600)
    except: pass
    try:
        page.click("button:has-text('איסוף עצמי')", timeout=3000)
        page.wait_for_timeout(3000)
    except: pass

    # Now the popup should show - click on the first branch (not the skip link)
    # Check for branch list
    page.screenshot(path=str(OUT / "debug10_popup.png"))

    # Use in-browser fetch to call the API within the session context
    print("Calling API from within browser context...")

    def api_call(endpoint, payload=None):
        if payload is None:
            payload = {}
        payload["requestNum"] = req_num[0]
        req_num[0] += 1
        resp = page.request.post(
            f"https://api.dominos.co.il/{endpoint}",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"}
        )
        try:
            return resp.json(), resp.status
        except:
            return {"raw": resp.text()[:300]}, resp.status

    # Get stores within browser session
    stores_resp, status = api_call("getStoreList")
    stores = stores_resp.get("data", [])
    print(f"Stores within browser session: {len(stores)}")
    if stores:
        print(f"First store: id={stores[0].get('id')} name={stores[0].get('name')}")
        store_id = stores[0]["id"]
    else:
        print("Raw response:", json.dumps(stores_resp)[:300])
        store_id = "501"

    # selectSubService
    r, s = api_call("selectSubService", {"subService": "pu"})
    print(f"selectSubService: {s} {r.get('status')}")

    # Try various endpoints for menu
    print("\nTrying menu endpoints within browser session:")
    for ep, payload in [
        ("selectStore", {"storeId": store_id}),
        ("setStore", {"storeId": store_id}),
        ("selectPickupStore", {"storeId": store_id}),
        ("getMenuData", {"storeId": store_id}),
        ("getMenu", {"storeId": store_id}),
        ("getOrderFlow", {"storeId": store_id}),
        ("getItemList", {"storeId": store_id}),
        ("getStoreDetails", {"storeId": store_id}),
        ("getCategories", {"storeId": store_id}),
        ("getOrderingStatus", {}),
    ]:
        r, status = api_call(ep, payload)
        body_str = json.dumps(r, ensure_ascii=False)
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body_str)
        size = len(body_str)
        print(f"  {ep}: {status} size={size} prices={prices[:5]} status_field={r.get('status','?')}")
        if prices:
            (OUT / f"FOUND_{ep}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  -> Saved FOUND_{ep}.json *** PRICES FOUND ***")

    b.close()
