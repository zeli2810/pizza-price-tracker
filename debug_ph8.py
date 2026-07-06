"""Find Pizza Hut menu/catalog via Atmos API directly."""
import sys, io, re, json, requests
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
OUT = Path(__file__).parent / "data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

ATMOS = "https://api-ns.atmos.co.il/rest/1"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Origin": "https://order.pizzahut.co.il",
    "Referer": "https://order.pizzahut.co.il/",
}

sess = requests.Session()
sess.headers.update(HEADERS)

# Step 1: Get brand info
print("1. getBrand...")
r = sess.get(f"{ATMOS}/restaurants/getBrand", params={"brandId": "pizzahut"})
brand = r.json()
print(f"   brand keys: {list(brand.get('result', {}).keys())[:15]}")
bid = brand.get("result", {}).get("id") or brand.get("result", {}).get("business_id", "")
print(f"   brand id: {bid}")

# Step 2: Get business
print("2. getBusiness...")
r = sess.get(f"{ATMOS}/restaurants/getBusiness", params={"brandId": "pizzahut"})
biz = r.json()
biz_result = biz.get("result", {})
print(f"   biz keys: {list(biz_result.keys())[:15]}")
biz_id = biz_result.get("id", "")
print(f"   business id: {biz_id}")

# Step 3: Get branches list and pick first
print("3. getBranchesList...")
r = sess.get(f"{ATMOS}/restaurants/getBranchesList", params={"brandId": "pizzahut"})
branches = r.json()
branch_list = branches.get("result", [])
if not isinstance(branch_list, list):
    branch_list = list(branches.get("result", {}).values()) if isinstance(branches.get("result"), dict) else []
print(f"   branches count: {len(branch_list)}")
if branch_list:
    first = branch_list[0]
    print(f"   first branch keys: {list(first.keys())[:15]}")
    branch_id = first.get("id") or first.get("branch_id") or first.get("external_branch_id", "")
    print(f"   branch id: {branch_id}")
    branch_name = first.get("name") or first.get("restaurant_name", "")
    print(f"   branch name: {branch_name}")
else:
    branch_id = ""

# Step 4: Try various menu/catalog endpoints
print("\n4. Trying menu/catalog endpoints...")
endpoints_to_try = [
    ("GET", f"{ATMOS}/catalog/getCatalog", {"branchId": branch_id, "brandId": "pizzahut"}),
    ("GET", f"{ATMOS}/catalog/getMenu", {"branchId": branch_id, "brandId": "pizzahut"}),
    ("GET", f"{ATMOS}/items/getItems", {"branchId": branch_id, "brandId": "pizzahut"}),
    ("GET", f"{ATMOS}/menu/getMenu", {"branchId": branch_id}),
    ("GET", f"{ATMOS}/restaurants/getCatalog", {"branchId": branch_id, "brandId": "pizzahut"}),
    ("GET", f"{ATMOS}/catalog/getCategories", {"branchId": branch_id, "brandId": "pizzahut"}),
    ("GET", f"{ATMOS}/restaurants/getBranchMenu", {"branchId": branch_id, "brandId": "pizzahut"}),
    ("GET", f"{ATMOS}/restaurants/getMenu", {"branchId": branch_id, "brandId": "pizzahut"}),
    ("GET", f"{ATMOS}/order/getMenu", {"branchId": branch_id}),
    ("GET", f"{ATMOS}/catalog/catalog", {"branchId": branch_id}),
]

for method, url, params in endpoints_to_try:
    try:
        resp = sess.get(url, params=params, timeout=10)
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', resp.text)
        real_prices = [p for p in prices if 30 < float(p) < 500]
        status = "[PRICES!]" if real_prices else f"({resp.status_code}, {len(resp.text)}b)"
        print(f"   {url.replace(ATMOS, 'API')} {status}")
        if real_prices:
            print(f"     Prices: {real_prices[:20]}")
            fname = re.sub(r'[^a-z0-9]', '_', url.split('/')[-1][:40])
            (OUT / f"PH8_{fname}.json").write_text(resp.text, encoding="utf-8")
            print(f"     Saved: PH8_{fname}.json")
            try:
                d = resp.json()
                print(f"     Keys: {list(d.keys())[:10]}")
            except: pass
    except Exception as e:
        print(f"   {url}: ERROR {e}")

# Step 5: Try getBranch (full) and look for catalog within it
print("\n5. getBranch full data...")
r = sess.get(f"{ATMOS}/restaurants/getBranch", params={"branchId": branch_id, "brandId": "pizzahut"})
branch_full = r.json()
result = branch_full.get("result", {})
print(f"   Full branch keys: {list(result.keys())}")

# Check if there's a catalog inside
for k in result.keys():
    v = result[k]
    if isinstance(v, (list, dict)) and len(str(v)) > 500:
        prices = re.findall(r'"[Pp]rice"\s*:\s*([\d.]+)', json.dumps(v))
        real = [p for p in prices if 30 < float(p) < 500]
        print(f"   Key '{k}': type={type(v).__name__}, len={len(str(v))}, real_prices={real[:5]}")
