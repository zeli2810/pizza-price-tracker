import json, sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
DATA = Path(__file__).parent / "data"

# Inspect store list
sl = json.loads((DATA / "api_getStoreList").read_text(encoding="utf-8"))
print("getStoreList top keys:", list(sl.keys()))
d = sl.get("data", {})
print("data keys:", list(d.keys())[:10] if isinstance(d, dict) else type(d))

if isinstance(d, dict):
    for k, v in d.items():
        if isinstance(v, list):
            print(f"\n'{k}' is a list of {len(v)} items")
            if v:
                print("  First item keys:", list(v[0].keys())[:15] if isinstance(v[0], dict) else v[0])
        else:
            print(f"'{k}': {str(v)[:100]}")
elif isinstance(d, list):
    print(f"data is list of {len(d)}")
    if d:
        print("First item:", json.dumps(d[0], ensure_ascii=False)[:300])
