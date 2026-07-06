import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from bs4 import BeautifulSoup
from pathlib import Path

BASE = Path(__file__).parent / "data"

for fname in ["pj_chrome.html", "pj_wayback.html"]:
    f = BASE / fname
    if not f.exists():
        continue
    html  = f.read_text(encoding="utf-8", errors="replace")
    soup  = BeautifulSoup(html, "html.parser")
    print(f"\n{'='*60}")
    print(f"File: {fname} ({len(html)}b)")
    print(f"Title: {soup.title.get_text()[:80] if soup.title else 'none'}")

    # Strip Wayback toolbar
    for sel in ["#wm-ipp-base", "#wm-ipp", ".wb-autocomplete-suggestions"]:
        for el in soup.select(sel): el.decompose()

    # 1. WooCommerce products
    products = []
    for prod in soup.select("li.product, .product-card, article.product, .product-item, .wc-block-grid__product"):
        name_el  = prod.select_one(".woocommerce-loop-product__title, h2, h3, .product-title, .entry-title, .wc-block-grid__product-title")
        price_el = prod.select_one(".woocommerce-Price-amount bdi, .price .amount, .price bdi, bdi, .woocommerce-Price-amount")
        name  = name_el.get_text(" ", strip=True)[:80]  if name_el  else ""
        price = price_el.get_text(" ", strip=True)[:30] if price_el else ""
        if name or price:
            products.append({"name": name, "price": price})
    print(f"\n--- WooCommerce products: {len(products)} ---")
    for p in products[:30]:
        print(f"  {p['name']!r:60} | {p['price']!r}")

    # 2. All bdi (WooCommerce price) elements
    bdis = soup.select("bdi")
    print(f"\n--- bdi elements: {len(bdis)} ---")
    seen = set()
    for bdi in bdis[:40]:
        t = bdi.get_text(strip=True)
        ctx = bdi.find_parent()
        # Walk up to find a meaningful parent with a name
        for _ in range(5):
            if ctx and ctx.get_text(strip=True) not in seen and len(ctx.get_text(strip=True)) > len(t):
                break
            if ctx: ctx = ctx.find_parent()
        ctx_text = ctx.get_text(" ", strip=True)[:100] if ctx else ""
        if t not in seen:
            seen.add(t)
            print(f"  {t!r:15} | ctx: {ctx_text[:90]!r}")

    # 3. ₪ in text nodes
    shekel_hits = []
    for el in soup.find_all(string=re.compile(r"[₪\d]")):
        t = el.strip()
        if not t or len(t) > 100:
            continue
        nums = re.findall(r"\d+(?:[.,]\d{1,2})?", t)
        for n in nums:
            v = float(n.replace(",", "."))
            if 20 < v < 800:
                parent = el.find_parent()
                ctx = parent.get_text(" ", strip=True)[:120] if parent else t
                shekel_hits.append({"price": v, "raw": t, "ctx": ctx})
    print(f"\n--- Numeric price hits: {len(shekel_hits)} ---")
    seen_ctx = set()
    for h in shekel_hits[:40]:
        key = f"{h['price']}|{h['ctx'][:50]}"
        if key not in seen_ctx:
            seen_ctx.add(key)
            print(f"  ₪{h['price']:6.1f} | {h['ctx'][:90]!r}")

    # 4. JSON-LD structured data
    print(f"\n--- JSON-LD ---")
    for script in soup.select("script[type='application/ld+json']"):
        try:
            d = json.loads(script.string or "")
            s = json.dumps(d, ensure_ascii=False)
            if any(k in s.lower() for k in ["price", "pizza", "product", "offer"]):
                print(s[:400])
        except Exception:
            pass

    # 5. Category URLs in nav
    print(f"\n--- Nav links ---")
    for a in soup.select("nav a, .menu a, .nav a, header a")[:20]:
        href = a.get("href", "")
        text = a.get_text(strip=True)[:40]
        if text and (href.startswith("http") or href.startswith("/")):
            print(f"  {text!r:30} -> {href[:60]}")
    break  # Process only the first successful file
