"""
CBS — private consumption expenditure per capita (excluding durable goods)
scraper.

Source: Israel CBS's "series generator" (מחולל סדרות), which turned out to be
a heavy multi-step Angular wizard — not economical to drive through a
browser. Instead this hits its own backend directly, found by reading the
wizard's JS (WizardHandler.ashx for the category tree, apis.cbs.gov.il for
the actual data):

  1. POST boardsgenerator.cbs.gov.il/Handlers/Sdarot/WizardHandler.ashx
     {mode:"TatNose", id_2:<subject>, id_3:<minorSubject>, code:<field>}
     walks the category tree (Field > Subject > MinorSubject > Area > cut >
     frequency) down to a leaf series id.
  2. GET apis.cbs.gov.il/series/data/list?id=<seriesId>&... returns the
     observations directly.

Series id 64081 = National accounts (from 1995, SNA 2008) > private
consumption expenditure > current+constant prices > "private consumption
expenditure excluding durable goods, per capita" > chained at 2020 prices,
seasonally adjusted > quarterly — confirmed via the response's own `path`
metadata, which echoes that exact category chain in Hebrew.

Output: data/cbs_private_consumption.json (latest snapshot) + Firestore
cbs_private_consumption/latest ({updated_at, unit, points:[{date,value}]}).
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

DATA_FILE = Path(__file__).parent / "data" / "cbs_private_consumption.json"

SERIES_ID = 64081
DATA_URL = (
    f"https://apis.cbs.gov.il/series/data/list?id={SERIES_ID}"
    "&startPeriod=01-1900&lang=he&format=json&download=false"
)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

MONTH_TO_QUARTER = {"03": "Q1", "06": "Q2", "09": "Q3", "12": "Q4"}


def _quarter_label(time_period):
    year, month = time_period.split("-")
    return f"{year}-{MONTH_TO_QUARTER.get(month, month)}"


def run_scrape(verbose=True):
    if verbose:
        print("  CBS private consumption per capita (ex-durables) — fetching series...")
    try:
        r = requests.get(DATA_URL, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"  ⚠ fetch error: {str(e)[:150]}")
        return []

    try:
        series = payload["DataSet"]["Series"][0]
        obs = series["obs"]
    except (KeyError, IndexError, TypeError):
        print("  ⚠ unexpected response shape — site structure may have changed.")
        return []

    points = [{"date": _quarter_label(o["TimePeriod"]), "value": float(o["Value"])} for o in obs]
    points.sort(key=lambda p: p["date"])

    if len(points) < 10:
        if verbose:
            print(f"  ⚠ only {len(points)} points found (< 10) — looks degraded; not overwriting existing data.")
        return []

    if verbose:
        print(f"    {len(points)} quarterly points · {points[0]['date']} .. {points[-1]['date']}")

    entry = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "unit": series.get("unit", {}).get("name", "ש\"ח") + " · רבעוני · משורשרים במחירי 2020 · מנוכה עונתיות",
        "source_url": "https://www.cbs.gov.il/he/Statistics/Pages/מחוללים/מחולל-סדרות.aspx?subject=37",
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
            db.collection("cbs_private_consumption").document("latest").set(entry)
            if verbose:
                print("  Synced CBS private consumption → Firestore ✓")
    except Exception as e:
        if verbose:
            print(f"  Firestore sync skipped: {e}")

    return points


if __name__ == "__main__":
    run_scrape()
