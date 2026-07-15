"""
One-time backfill: push the historical Pais Plus offers already stored in
data/paisplus/offers.json into Firestore (paisplus_offers/{date}).

Useful because the live scraper is sometimes blocked by the target site, so
Firestore may be missing days that the committed JSON history already has.
Run via the "Backfill Firestore from JSON" GitHub Actions workflow (which
provides FIREBASE_SERVICE_ACCOUNT), or locally with credentials configured.
"""

import json
from pathlib import Path

import firestore_sync

ROOT = Path(__file__).parent
OFFERS_FILE = ROOT / "data" / "paisplus" / "offers.json"
WOLT_FILE = ROOT / "data" / "wolt_offers.json"


def group_by_date(offers):
    by_date = {}
    for o in offers:
        by_date.setdefault(o.get("date"), []).append(o)
    return by_date


def main():
    if not firestore_sync.is_enabled():
        print("Firestore not enabled (no credentials) — nothing to backfill.")
        return

    # Pais Plus offers
    if OFFERS_FILE.exists():
        by_date = group_by_date(json.load(open(OFFERS_FILE, encoding="utf-8-sig")))
        n = sum(1 for date, day in sorted(by_date.items())
                if date and firestore_sync.push_paisplus_offers(day, date=date))
        print(f"Backfilled {n} Pais Plus date(s).")

    # Wolt offers (same shape) → wolt_offers collection
    if WOLT_FILE.exists():
        db = firestore_sync.get_client()
        by_date = group_by_date(json.load(open(WOLT_FILE, encoding="utf-8-sig")))
        n = 0
        for date, day in sorted(by_date.items()):
            if not date:
                continue
            db.collection("wolt_offers").document(date).set({"date": date, "offers": day})
            n += 1
        print(f"Backfilled {n} Wolt date(s).")


if __name__ == "__main__":
    main()
