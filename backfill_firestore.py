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

OFFERS_FILE = Path(__file__).parent / "data" / "paisplus" / "offers.json"


def group_by_date(offers):
    by_date = {}
    for o in offers:
        by_date.setdefault(o.get("date"), []).append(o)
    return by_date


def main():
    if not firestore_sync.is_enabled():
        print("Firestore not enabled (no credentials) — nothing to backfill.")
        return
    if not OFFERS_FILE.exists():
        print(f"{OFFERS_FILE} not found.")
        return

    offers = json.load(open(OFFERS_FILE, encoding="utf-8-sig"))
    by_date = group_by_date(offers)
    n = 0
    for date, day_offers in sorted(by_date.items()):
        if not date:
            continue
        if firestore_sync.push_paisplus_offers(day_offers, date=date):
            n += 1
    print(f"Backfilled {n} Pais Plus date(s) into Firestore.")


if __name__ == "__main__":
    main()
