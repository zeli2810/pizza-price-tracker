"""
Firestore sync layer for the Pizza Price Tracker (hybrid architecture).

The heavy Playwright scraping keeps running on GitHub Actions (free, reliable).
This module pushes the results into Google Firestore so the Firebase-hosted
dashboard can read them directly with the client SDK.

Firestore layout
----------------
  price_history/{YYYY-MM-DD}   -> one document per day
      { date, timestamp, chains: { <chain>: { pu:{...}, dlv:{...},
                                              branch_count, error } } }

  meta/status                  -> rolling per-site status (for the dashboard)
      { last_run,
        sites: { <chain>: { ok, last_success, last_attempt, error } } }

Credentials
-----------
A Google service-account key is required to WRITE to Firestore. It is resolved
(in order) from:
  1. FIREBASE_SERVICE_ACCOUNT       - the full JSON key, inline (GitHub secret)
  2. FIREBASE_SERVICE_ACCOUNT_FILE  - path to a JSON key file
  3. GOOGLE_APPLICATION_CREDENTIALS - standard Google env var (path)

If none are present (e.g. a plain local run), every function here becomes a
no-op and just logs a notice — the scraper still works and writes its JSON.
Reading the dashboard needs NO key; that goes through public Firestore rules.
"""

import json
import os
import sys

# firebase-admin is optional at runtime: if it isn't installed (or no creds are
# configured) we degrade gracefully instead of crashing the scraper.
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    _ADMIN_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _ADMIN_AVAILABLE = False

_client = None            # cached Firestore client
_init_attempted = False   # so we only try (and warn) once per process


def _log(msg):
    print(f"    [firestore] {msg}", file=sys.stderr)


def _load_credentials():
    """Return a firebase_admin credential object, or None if unavailable."""
    inline = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if inline:
        try:
            info = json.loads(inline)
            return credentials.Certificate(info)
        except Exception as e:
            _log(f"FIREBASE_SERVICE_ACCOUNT is set but not valid JSON: {e}")
            return None

    path = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_FILE")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    if path and os.path.exists(path):
        try:
            return credentials.Certificate(path)
        except Exception as e:
            _log(f"could not load key file {path}: {e}")
            return None

    return None


def get_client():
    """Lazily create and cache the Firestore client. Returns None if disabled."""
    global _client, _init_attempted
    if _client is not None:
        return _client
    if _init_attempted:
        return None
    _init_attempted = True

    if not _ADMIN_AVAILABLE:
        _log("firebase-admin not installed — skipping Firestore sync "
             "(pip install firebase-admin to enable).")
        return None

    cred = _load_credentials()
    if cred is None:
        _log("no service-account credentials found — skipping Firestore sync. "
             "Set FIREBASE_SERVICE_ACCOUNT to enable.")
        return None

    try:
        # Reuse the default app if this process already initialised one.
        try:
            app = firebase_admin.get_app()
        except ValueError:
            app = firebase_admin.initialize_app(cred)
        _client = firestore.client(app)
        _log("Firestore client ready ✓")
        return _client
    except Exception as e:
        _log(f"failed to initialise Firestore: {e}")
        return None


def is_enabled():
    return get_client() is not None


def push_entry(entry):
    """
    Write one daily entry (as produced by the scrapers) to
    price_history/{date} and refresh meta/status. Safe no-op when disabled.

    `entry` shape: {"date","timestamp","chains": {chain: {...}}}
    Returns True on success, False otherwise.
    """
    db = get_client()
    if db is None:
        return False

    date = entry.get("date")
    if not date:
        _log("entry has no 'date' — refusing to write.")
        return False

    try:
        # merge=True so a later run (e.g. the separate Pais Plus workflow) can
        # add its own chain to the same day's document without clobbering the
        # chains already written by an earlier run.
        db.collection("price_history").document(date).set(entry, merge=True)
        _update_status(db, entry)
        _log(f"pushed price_history/{date} ✓")
        return True
    except Exception as e:
        _log(f"push_entry failed: {e}")
        return False


def _chain_has_prices(chain_data):
    """True if any pu/dlv price point is populated for this chain."""
    for svc in ("pu", "dlv"):
        block = chain_data.get(svc) or {}
        if any(v is not None for v in block.values()):
            return True
    return False


def _update_status(db, entry):
    """Merge per-site success/failure info into meta/status."""
    from firebase_admin import firestore as _fs  # local import for SERVER_TIMESTAMP
    timestamp = entry.get("timestamp")
    sites = {}
    for chain, data in (entry.get("chains") or {}).items():
        ok = _chain_has_prices(data) and not data.get("error")
        site_status = {
            "last_attempt": timestamp,
            "ok": ok,
            "error": data.get("error"),
        }
        if ok:
            site_status["last_success"] = timestamp
        sites[chain] = site_status

    payload = {
        "last_run": timestamp,
        "updated_at": _fs.SERVER_TIMESTAMP,
        "sites": sites,
    }
    # merge=True so a site missing from this run keeps its previous last_success.
    db.collection("meta").document("status").set(payload, merge=True)


def mark_site_status(chain, ok, error=None, timestamp=None):
    """Update the status of a single site independently (used by paisplus etc.)."""
    db = get_client()
    if db is None:
        return False
    from firebase_admin import firestore as _fs
    site_status = {"last_attempt": timestamp, "ok": ok, "error": error}
    if ok and timestamp:
        site_status["last_success"] = timestamp
    try:
        db.collection("meta").document("status").set(
            {"sites": {chain: site_status}, "updated_at": _fs.SERVER_TIMESTAMP},
            merge=True,
        )
        return True
    except Exception as e:
        _log(f"mark_site_status failed: {e}")
        return False


def push_paisplus_offers(offers, date=None):
    """
    Store the Pais Plus offers list (deal-based data) under
    paisplus_offers/{date}. Kept separate from the menu-price comparison
    because its shape is different (a list of promotional offers).
    """
    db = get_client()
    if db is None:
        return False
    if not offers:
        return False
    date = date or (offers[0].get("date") if offers else None)
    if not date:
        return False
    try:
        db.collection("paisplus_offers").document(date).set({
            "date": date,
            "offers": offers,
        })
        _log(f"pushed paisplus_offers/{date} ({len(offers)} offers) ✓")
        return True
    except Exception as e:
        _log(f"push_paisplus_offers failed: {e}")
        return False
