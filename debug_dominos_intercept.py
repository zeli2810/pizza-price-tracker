"""Intercept all API calls dominos.co.il makes and log them."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "data"
calls = []

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(locale="he-IL", viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    def on_request(req):
        if "api.dominos.co.il" in req.url:
            try:
                body = req.post_data_json or {}
            except Exception:
                body = {}
            calls.append({"dir": "REQ", "url": req.url, "body": body})

    def on_response(resp):
        if "api.dominos.co.il" in resp.url:
            try:
                body = resp.json()
            except Exception:
                body = {}
            # Only log status + small subset
            calls.append({"dir": "RES", "url": resp.url,
                          "status": body.get("status"),
                          "keys": list(body.get("data", {}).keys())[:10] if isinstance(body.get("data"), dict) else []})

    page.on("request", on_request)
    page.on("response", on_response)

    print("Loading dominos.co.il...")
    page.goto("https://www.dominos.co.il/menu", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    print(f"URL: {page.url}")

    browser.close()

out = OUT / "dominos_intercept.json"
out.write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Logged {len(calls)} calls to {out}")
for c in calls:
    if c["dir"] == "REQ":
        ep = c["url"].split("dominos.co.il/")[-1]
        print(f"  -> {ep}  body={json.dumps(c['body'], ensure_ascii=False)[:120]}")
    else:
        ep = c["url"].split("dominos.co.il/")[-1]
        print(f"  <- {ep}  status={c['status']} data_keys={c['keys']}")
