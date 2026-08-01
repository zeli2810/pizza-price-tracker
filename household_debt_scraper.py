"""
Bank of Israel — "Total household debt balance" scraper.

Source: the BOI Edge Fusion Data Browser (https://edge.boi.gov.il/#/), the
"Debt and credit aggregates" dataset (dataflow BOI.STATISTICS:DEBT_AGG,
category "Money and Debt aggregates" — the "Households" cut the user asked
for is a dimension VALUE within this one dataflow, not a separate dataset).
Same SDMX REST API approach as credit_card_purchases_scraper.py: fetch the
whole dataflow (~1MB, 248 series) and filter client-side.

The target series is identified by SERIES_CODE="CRA_OUT_0204" — its own name
in the response ("Total debt balance of households") confirms it, and its
full dimension combo is: FREQ=Q (quarterly), DATA_TYPE=STK (stock/balance,
not a % or a flow), DEBT_CREDIT=D (debt, borrower's side), BORROWING_SECTOR=
S14_S15_L (households incl. non-profits serving them), LENDING_SECTOR=LENDC_L
(all lending sectors combined), INDEXATION_TYPE=_T (all index types
combined) — i.e. the single all-in headline figure, not a sub-breakdown.
Unit: NIS billions (UNIT_MULT=9, UNIT_MEASURE=ILS). Data starts 1992-Q3;
the dashboard defaults its view to ~2021 onward per the user's ask, via its
own period selector, while this scraper keeps the full history for export.

Output: data/household_debt.json (latest snapshot) + Firestore
household_debt/latest ({updated_at, unit, points:[{date,value}]}).
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

DATA_FILE = Path(__file__).parent / "data" / "household_debt.json"

DATA_URL = (
    "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/"
    "BOI.STATISTICS/DEBT_AGG/1.0/?format=sdmx-json&dimensionAtObservation=AllDimensions"
)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

TARGET_SERIES_CODE = "CRA_OUT_0204"  # "Total debt balance of households"


def run_scrape(verbose=True):
    if verbose:
        print("  BOI household debt — fetching DEBT_AGG dataflow...")
    try:
        r = requests.get(DATA_URL, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"  ⚠ fetch error: {str(e)[:150]}")
        return []

    dims = payload["data"]["structure"]["dimensions"]["observation"]
    dim_ids = [d["id"] for d in dims]
    sc_idx = dim_ids.index("SERIES_CODE")
    time_idx = dim_ids.index("TIME_PERIOD")
    time_values = [v["id"] for v in dims[time_idx]["values"]]
    sc_values = dims[sc_idx]["values"]
    target_pos = next((i for i, v in enumerate(sc_values) if v["id"] == TARGET_SERIES_CODE), None)
    if target_pos is None:
        print(f"  ⚠ series '{TARGET_SERIES_CODE}' not found in response — site structure may have changed.")
        return []

    obs = payload["data"]["dataSets"][0]["observations"]
    points = []
    for key, val in obs.items():
        idx = [int(x) for x in key.split(":")]
        if idx[sc_idx] == target_pos:
            try:
                points.append({"date": time_values[idx[time_idx]], "value": float(val[0])})
            except (TypeError, ValueError):
                continue
    points.sort(key=lambda p: p["date"])

    if len(points) < 20:
        if verbose:
            print(f"  ⚠ only {len(points)} points found (< 20) — looks degraded; not overwriting existing data.")
        return []

    if verbose:
        print(f"    {len(points)} quarterly points · {points[0]['date']} .. {points[-1]['date']}")

    entry = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "unit": "מיליארדי ש\"ח · רבעוני · יתרת חוב משקי בית (כולל מלכ\"רים המשרתים משקי בית), כל המלווים",
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
            db.collection("household_debt").document("latest").set(entry)
            if verbose:
                print("  Synced household debt → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    return points


if __name__ == "__main__":
    run_scrape()
