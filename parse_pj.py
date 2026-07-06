import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup
from pathlib import Path

BASE = Path(__file__).parent / "data"

# Try cache file
for fname in ["pj_archive.html", "pj_cache.html", "pj_requests.html", "pj_mobile.html", "pj_playwright_1.html"]:
    f = BASE / fname
    if f.exists():
        html = f.read_text(encoding="utf-8", errors="replace")
        print(f"Reading {fname} ({len(html)}b)")
        break
else:
    print("No HTML file found"); sys.exit(1)

soup = BeautifulSoup(html, "html.parser")
print("Title:", soup.title.get_text() if soup.title else "(none)")
print()

# 1. Find all WooCommerce product cards
print("=== Products (WooCommerce) ===")
for prod in soup.select("li.product, .product-card, .product-item, article.product")[:20]:
    name  = (prod.select_one(".woocommerce-loop-product__title, h2, h3, .product-title") or "")
    price = (prod.select_one(".woocommerce-Price-amount, .price, .amount") or "")
    n = name.get_text(" ", strip=True)[:60] if name else ""
    p = price.get_text(" ", strip=True)[:30] if price else ""
    if n or p:
        print(f"  {n!r:50} | {p!r}")

# 2. All elements containing ₪
print()
print("=== Shekel prices ===")
seen = set()
for el in soup.find_all(string=re.compile(r"₪")):
    t = el.strip()
    if t and t not in seen:
        seen.add(t)
        parent = el.find_parent()
        ctx = parent.get_text(" ", strip=True)[:100] if parent else ""
        print(f"  {t!r:25} | ctx: {ctx[:80]!r}")

# 3. All numeric lines from body text
print()
print("=== Price-like lines ===")
text = soup.get_text("\n")
lines = [l.strip() for l in text.splitlines() if l.strip() and re.search(r"\d{2,3}", l.strip()) and len(l.strip()) < 150]
seen2 = set()
for l in lines[:60]:
    if l not in seen2:
        seen2.add(l)
        print(f"  {l[:120]!r}")

# 4. JSON-LD / structured data
print()
print("=== JSON-LD ===")
for script in soup.select("script[type='application/ld+json']"):
    try:
        d = json.loads(script.string)
        print(json.dumps(d, ensure_ascii=False)[:300])
    except Exception:
        pass
