"""
Aggressive Papa John's scraper with stealth + screenshot OCR fallback.
Tries 5 approaches in order, saves screenshots for visual parsing.
"""
import sys, io, json, re, time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "data"
UA  = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0.0.0 Safari/537.36")

STEALTH_JS = """
// Remove webdriver traces
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['he-IL','he','en-US','en']});
window.chrome = {runtime: {}};
Object.defineProperty(navigator, 'permissions', {
  get: () => ({query: () => Promise.resolve({state: 'granted'})})
});
"""

URLS_TO_TRY = [
    "https://www.papajohns.co.il/shop/",
    "https://www.papajohns.co.il/product-category/pizzas/",
    "https://www.papajohns.co.il/",
    "https://www.papajohns.co.il/menu/",
    "https://papajohns.co.il/shop/",
]

def try_requests():
    """Approach 1: plain requests with realistic headers."""
    print("\n[1] requests + realistic headers...")
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    sess = requests.Session()
    # First hit homepage to get cookies
    try:
        r0 = sess.get("https://www.papajohns.co.il/", headers=headers, timeout=15)
        print(f"   homepage: {r0.status_code} ({len(r0.text)}b)")
        time.sleep(1)
        r1 = sess.get("https://www.papajohns.co.il/shop/", headers={**headers, "Referer": "https://www.papajohns.co.il/"}, timeout=15)
        print(f"   /shop/: {r1.status_code} ({len(r1.text)}b)")
        if r1.status_code == 200 and len(r1.text) > 5000:
            OUT.joinpath("pj_requests.html").write_text(r1.text, encoding="utf-8")
            return r1.text
    except Exception as e:
        print(f"   error: {e}")
    return None

def try_woo_api():
    """Approach 2: WooCommerce Store API (public, no auth)."""
    print("\n[2] WooCommerce Store API...")
    endpoints = [
        "https://www.papajohns.co.il/wp-json/wc/store/v1/products?per_page=100",
        "https://www.papajohns.co.il/wp-json/wc/v3/products?per_page=100&consumer_key=&consumer_secret=",
        "https://www.papajohns.co.il/wp-json/wc/store/v1/products?category=pizzas&per_page=50",
        "https://www.papajohns.co.il/?wc-ajax=get_refreshed_fragments",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=10)
            print(f"   {url.split('/')[-1][:40]}: {r.status_code} ({len(r.text)}b)")
            if r.status_code == 200 and len(r.text) > 100:
                OUT.joinpath("pj_api.json").write_text(r.text, encoding="utf-8")
                return r.json()
        except Exception as e:
            print(f"   error: {e}")
    return None

def try_playwright_stealth(headless=True):
    """Approach 3: Playwright with full stealth."""
    mode = "headless" if headless else "headed"
    print(f"\n[3] Playwright stealth ({mode})...")
    screenshots = []

    with sync_playwright() as pw:
        # Try real Chrome first, fall back to Chromium
        for launch_fn, name in [(pw.chromium.launch, "chromium")]:
            try:
                browser = launch_fn(
                    headless=headless,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        f"--user-agent={UA}",
                    ]
                )
                ctx = browser.new_context(
                    locale="he-IL",
                    timezone_id="Asia/Jerusalem",
                    viewport={"width": 1440, "height": 900},
                    user_agent=UA,
                    extra_http_headers={
                        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
                        "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                    },
                    java_script_enabled=True,
                )
                ctx.add_init_script(STEALTH_JS)
                page = ctx.new_page()

                # Intercept all API responses
                api_data = {}
                def on_resp(resp):
                    url = resp.url
                    if any(x in url for x in ["wp-json", "wc/store", "product", "menu", "api"]):
                        try:
                            body = resp.text()
                            if len(body) > 200:
                                api_data[url] = body[:5000]
                                if "price" in body.lower() or "מחיר" in body:
                                    print(f"   API hit: {url[:70]} ({len(body)}b)")
                        except Exception:
                            pass
                page.on("response", on_resp)

                # Navigate with delay between pages
                for i, url in enumerate(URLS_TO_TRY[:3]):
                    try:
                        resp = page.goto(url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(3000)
                        sc_path = str(OUT / f"pj_stealth_{i+1}.png")
                        page.screenshot(path=sc_path, full_page=True)
                        screenshots.append(sc_path)
                        status = resp.status if resp else "?"
                        title  = page.title()
                        body_len = len(page.content())
                        print(f"   [{i+1}] {url}: HTTP {status} | '{title}' | {body_len}b")

                        if status == 200 and "Access Denied" not in title and body_len > 5000:
                            html = page.content()
                            OUT.joinpath(f"pj_playwright_{i+1}.html").write_text(html, encoding="utf-8")
                            # Try to dismiss popups and navigate to menu
                            for sel in ["button:has-text('סגור')", "button:has-text('אישור')", ".popup-close", "[aria-label='Close']"]:
                                try: page.click(sel, timeout=1500)
                                except Exception: pass
                            # Scroll to trigger lazy loads
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                            page.wait_for_timeout(1500)
                            page.screenshot(path=str(OUT / f"pj_stealth_{i+1}_scrolled.png"), full_page=True)
                            screenshots.append(str(OUT / f"pj_stealth_{i+1}_scrolled.png"))
                            break
                        time.sleep(2)
                    except Exception as e:
                        print(f"   [{i+1}] {url}: error — {str(e)[:80]}")

                # Save API responses
                if api_data:
                    OUT.joinpath("pj_api_intercept.json").write_text(json.dumps(api_data, ensure_ascii=False, indent=2), encoding="utf-8")

                browser.close()
                break
            except Exception as e:
                print(f"   {name} failed: {e}")

    return screenshots

def try_mobile_ua():
    """Approach 4: Mobile user-agent (sometimes bypasses CDN)."""
    print("\n[4] Mobile UA...")
    mobile_ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                 "Version/17.0 Mobile/15E148 Safari/604.1")
    headers = {
        "User-Agent": mobile_ua,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "he-IL,he;q=0.9",
    }
    for url in URLS_TO_TRY[:2]:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            print(f"   {url}: {r.status_code} ({len(r.text)}b)")
            if r.status_code == 200 and len(r.text) > 5000:
                OUT.joinpath("pj_mobile.html").write_text(r.text, encoding="utf-8")
                return r.text
        except Exception as e:
            print(f"   error: {e}")
    return None

def try_google_cache():
    """Approach 5: Google Cache."""
    print("\n[5] Google Cache / Archive...")
    cache_urls = [
        "https://webcache.googleusercontent.com/search?q=cache:papajohns.co.il/shop/",
        "https://archive.org/wayback/available?url=papajohns.co.il/shop/",
    ]
    for url in cache_urls:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=12)
            print(f"   {url[:60]}: {r.status_code} ({len(r.text)}b)")
            if r.status_code == 200 and len(r.text) > 1000:
                data = r.json() if "wayback" in url else r.text
                if isinstance(data, dict):
                    closest = data.get("archived_snapshots", {}).get("closest", {})
                    if closest.get("available"):
                        archive_url = closest["url"]
                        print(f"   Archive URL: {archive_url}")
                        r2 = requests.get(archive_url, headers={"User-Agent": UA}, timeout=15)
                        if r2.status_code == 200:
                            OUT.joinpath("pj_archive.html").write_text(r2.text, encoding="utf-8")
                            return r2.text
                else:
                    if "papa" in data.lower() or "פיצ" in data:
                        OUT.joinpath("pj_cache.html").write_text(data, encoding="utf-8")
                        return data
        except Exception as e:
            print(f"   error: {e}")
    return None


if __name__ == "__main__":
    print("=" * 60)
    print("Papa John's Israel — Aggressive Scrape Debug")
    print("=" * 60)

    results = {}

    # 1. Plain requests
    html = try_requests()
    if html: results["requests"] = html

    # 2. WooCommerce API
    api = try_woo_api()
    if api: results["woo_api"] = api

    # 3. Playwright stealth (headless)
    shots = try_playwright_stealth(headless=True)
    results["screenshots"] = shots
    print(f"\n  Screenshots saved: {shots}")

    # 4. Mobile UA
    if not results.get("requests"):
        html_m = try_mobile_ua()
        if html_m: results["mobile"] = html_m

    # 5. Archive
    if not any(results.get(k) for k in ["requests", "woo_api", "mobile"]):
        html_a = try_google_cache()
        if html_a: results["archive"] = html_a

    print("\n" + "=" * 60)
    print("Summary:")
    for k, v in results.items():
        if k == "screenshots":
            print(f"  screenshots: {len(v)} files")
        else:
            print(f"  {k}: {'✓ got data' if v else '✗ failed'}")
    print("=" * 60)
