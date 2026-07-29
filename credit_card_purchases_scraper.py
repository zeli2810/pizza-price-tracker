"""
Bank of Israel — "Total credit card purchases" scraper.

Source: the BOI Edge Fusion Data Browser (https://edge.boi.gov.il/#/), dataset
"רכישות בכרטיסי אשראי" (Real Economic Activity > Principal Industries),
dataflow BOI.STATISTICS:CCP(1.0). The browser's own UI (autocomplete + tree
navigation) turned out to be unautomatable reliably, so this hits the SDMX
REST API directly — found by grepping the site's own minified JS bundle for
its `DataQueryUtil.buildRESTUrl` method, which builds:
  {env}/data/dataflow/{agency}/{id}/{version}/{seriesKeys?}?params
With no series keys, that returns the WHOLE dataflow (all 42 industry-activity
breakdowns) in one shot — small enough (~130k observations) to just fetch and
filter client-side for ACTIVITY="_T" (the "Total", i.e. all industries).

Series properties (from the response's own attributes): daily, current
prices, NIS millions, calendar+seasonally adjusted, 7-period (day) moving
average, summed through period. Data starts 2016-01-07.

Output: data/credit_card_purchases.json (latest snapshot) + Firestore
credit_card_purchases/latest ({updated_at, unit, points:[{date,value}]}).
"""

import json
import sys
import io
from pathlib import Path
from datetime import datetime

import requests

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DATA_FILE = Path(__file__).parent / "data" / "credit_card_purchases.json"

DATA_URL = (
    "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/"
    "BOI.STATISTICS/CCP/1.0/?format=sdmx-json&dimensionAtObservation=AllDimensions"
)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

TOTAL_ACTIVITY_CODE = "_T"


def run_scrape(verbose=True):
    if verbose:
        print("  BOI credit card purchases — fetching CCP dataflow...")
    try:
        r = requests.get(DATA_URL, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"  ⚠ fetch error: {str(e)[:150]}")
        return []

    dims = payload["data"]["structure"]["dimensions"]["observation"]
    dim_ids = [d["id"] for d in dims]
    act_idx = dim_ids.index("ACTIVITY")
    time_idx = dim_ids.index("TIME_PERIOD")
    time_values = [v["id"] for v in dims[time_idx]["values"]]
    act_values = dims[act_idx]["values"]
    total_pos = next((i for i, v in enumerate(act_values) if v["id"] == TOTAL_ACTIVITY_CODE), None)
    if total_pos is None:
        print("  ⚠ 'Total' (_T) activity code not found in response — site structure may have changed.")
        return []

    obs = payload["data"]["dataSets"][0]["observations"]
    points = []
    for key, val in obs.items():
        idx = [int(x) for x in key.split(":")]
        if idx[act_idx] == total_pos:
            try:
                points.append({"date": time_values[idx[time_idx]], "value": float(val[0])})
            except (TypeError, ValueError):
                continue
    points.sort(key=lambda p: p["date"])

    if len(points) < 100:
        if verbose:
            print(f"  ⚠ only {len(points)} points found (< 100) — looks degraded; not overwriting existing data.")
        return []

    if verbose:
        print(f"    {len(points)} daily points · {points[0]['date']} .. {points[-1]['date']}")

    entry = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "unit": "NIS millions · daily · calendar+seasonally adjusted · 7-day moving average",
        "source_url": "https://edge.boi.gov.il/#/",
        "points": points,
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"  נשמרו → {DATA_FILE}")

    try:
        import firestore_sync
        if firestore_sync.is_enabled():
            db = firestore_sync.get_client()
            db.collection("credit_card_purchases").document("latest").set(entry)
            if verbose:
                print("  Synced credit card purchases → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    return points


if __name__ == "__main__":
    run_scrape()
