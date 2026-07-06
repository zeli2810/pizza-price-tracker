"""Fetch Domino's API endpoints to find pricing data."""
import sys, io, json, re
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(locale="he-IL", viewport={"width":1280,"height":900}, user_agent=UA)
    page = ctx.new_page()

    # ── 1. Capture store list and menu API calls ──
    api_responses = {}

    def on_response(resp):
        url = resp.url
        if "api.dominos.co.il" in url or "dictionaryWithAssets" in url or "dictionary.he.be" in url:
            try:
                body = resp.text()
                key = url.split("/")[-1].split("?")[0][:50]
                if url not in api_responses:
                    api_responses[url] = body
                    print(f"Captured: {url[:100]} ({len(body)} bytes)")
            except Exception as e:
                print(f"Could not read {url[:80]}: {e}")

    page.on("response", on_response)

    page.goto("https://www.dominos.co.il", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    page.click("div:has-text('תפריט והזמנה')", timeout=3000)
    page.wait_for_timeout(500)
    page.click("button:has-text('איסוף עצמי')", timeout=3000)
    page.wait_for_timeout(4000)

    # ── 2. Analyze the responses ──
    print("\n\n=== ANALYZING RESPONSES ===\n")
    for url, body in api_responses.items():
        print(f"\n--- {url[:80]} ---")
        try:
            data = json.loads(body)
            # Look for price-related keys
            body_str = json.dumps(data, ensure_ascii=False)
            prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', body_str)
            if prices:
                print(f"  Prices found: {prices[:20]}")
            # If it's a store list, show store IDs
            if isinstance(data, dict):
                print(f"  Top-level keys: {list(data.keys())[:10]}")
                if "Stores" in data or "stores" in data:
                    stores = data.get("Stores") or data.get("stores")
                    if stores:
                        print(f"  Stores count: {len(stores)}")
                        if stores:
                            print(f"  First store: {json.dumps(stores[0], ensure_ascii=False)[:200]}")
            elif isinstance(data, list) and data:
                print(f"  List length: {len(data)}")
                print(f"  First item keys: {list(data[0].keys())[:10] if isinstance(data[0], dict) else 'n/a'}")
        except Exception as e:
            print(f"  Not JSON or parse error: {e}")
            print(f"  Preview: {body[:200]}")

    # Save all captured data
    for url, body in api_responses.items():
        fname = re.sub(r'[^a-zA-Z0-9._-]', '_', url.split("/")[-1].split("?")[0])[:40]
        (OUT / f"api_{fname}").write_text(body, encoding="utf-8")

    b.close()
