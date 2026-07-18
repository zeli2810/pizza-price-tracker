"""
Marketing Idea Tracker — daily collector.

For each RSS source (with auto-discovery of the feed URL), fetches new items,
pulls the full article text, sends it to the Claude API to extract a structured
marketing idea, deduplicates, and stores it in Firestore (marketing_ideas).

Adding a source = one line in SOURCES below.

Env vars:
  ANTHROPIC_API_KEY          - required for extraction (never hard-coded)
  FIREBASE_SERVICE_ACCOUNT*  - to write to Firestore (see firestore_sync.py)
  MARKETING_MODEL            - optional model override (default claude-sonnet-5)
  MARKETING_MAX_PER_SOURCE   - optional cap of new items per source per run (default 8)
"""

import os
import re
import sys
import time
import json
import hashlib
from datetime import datetime, timezone

import requests
import feedparser
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from multi_scraper import UA  # sets UTF-8 stdout on Windows too

# ── sources (add one line to add a source) ─────────────────────────────────────
# feed_url "" → auto-discover from the homepage.
SOURCES = [
    {"name": "QSR Magazine",                 "home": "https://www.qsrmagazine.com",            "feed_url": ""},
    {"name": "Nation's Restaurant News",     "home": "https://www.nrn.com",                    "feed_url": ""},
    {"name": "Restaurant Business Magazine", "home": "https://www.restaurantbusinessonline.com","feed_url": ""},
    {"name": "Ad Age",                       "home": "https://adage.com",                      "feed_url": ""},
    {"name": "Marketing Dive",               "home": "https://www.marketingdive.com",          "feed_url": ""},
    {"name": "The Drum",                     "home": "https://www.thedrum.com",                "feed_url": ""},
    {"name": "Adweek",                       "home": "https://www.adweek.com",                 "feed_url": ""},
]

# Extraction backend: "ollama" (local, free) | "claude" (API) | "heuristic" (rules)
EXTRACTOR = os.environ.get("MARKETING_EXTRACTOR", "ollama").lower()
MODEL = os.environ.get("MARKETING_MODEL", "claude-sonnet-5")          # for claude mode
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")           # for ollama mode (good Hebrew+JSON)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MAX_PER_SOURCE = int(os.environ.get("MARKETING_MAX_PER_SOURCE", "8"))
FUZZY_THRESHOLD = 82  # rapidfuzz 0-100 (spec: 0.82)
CATEGORIES = ["LTO", "מבצע מחיר", "שיתוף פעולה", "נאמנות לקוחות",
              "סטאנט שיווקי", "קמפיין דיגיטלי-חברתי", "אחר"]

SYSTEM_PROMPT = (
    "You extract a structured marketing idea from a fast-food / restaurant "
    "marketing article. Respond with ONLY a JSON object, no prose, with exactly "
    "these keys:\n"
    '{"brand","campaign_name","category","summary","evidence_of_success","confidence"}\n'
    "- brand: the brand/chain name.\n"
    "- campaign_name: the campaign/promotion name.\n"
    "- category: EXACTLY one of: LTO / מבצע מחיר / שיתוף פעולה / נאמנות לקוחות / "
    "סטאנט שיווקי / קמפיין דיגיטלי-חברתי / אחר.\n"
    "- summary: 2-4 sentence summary of the idea, in English.\n"
    "- evidence_of_success: a concrete quote/number from the article showing "
    "success (sales, engagement, awards), or null if none.\n"
    "- confidence: high / medium / low — how strong the evidence in the article is.\n"
    "If the article is not about a specific marketing campaign, set brand and "
    "campaign_name to null."
)

_log_lines = []
def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, file=sys.stderr)
    _log_lines.append(line)


def _id_for_url(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


# ── RSS discovery + fetching ───────────────────────────────────────────────────
def discover_feed(home):
    """Find the RSS feed URL for a site (per the spec's fallback chain)."""
    try:
        r = requests.get(home, headers={"User-Agent": UA}, timeout=20)
        soup = BeautifulSoup(r.text, "lxml")
        link = soup.find("link", rel="alternate", type=re.compile(r"rss|atom"))
        if link and link.get("href"):
            return requests.compat.urljoin(home, link["href"])
    except Exception as e:
        log(f"  discover error on {home}: {str(e)[:60]}")
    for path in ("/feed", "/rss", "/feed.xml", "/rss.xml"):
        url = home.rstrip("/") + path
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
            if r.ok and ("xml" in r.headers.get("content-type", "") or "<rss" in r.text[:500] or "<feed" in r.text[:500]):
                return url
        except Exception:
            pass
    return None


def fetch_article_text(url):
    """Load the source page and extract the main text (best-effort)."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        main = soup.find("article") or soup.find("main") or soup.body
        text = main.get_text(" ", strip=True) if main else ""
        return re.sub(r"\s+", " ", text)[:12000]
    except Exception as e:
        log(f"  article fetch error: {str(e)[:60]}")
        return ""


# ── extraction (Ollama / Claude / heuristic) ───────────────────────────────────
def _validate(idea):
    if not isinstance(idea, dict):
        return None
    if not idea.get("brand") and not idea.get("campaign_name"):
        return None  # not a specific campaign
    if idea.get("category") not in CATEGORIES:
        idea["category"] = "אחר"
    if idea.get("confidence") not in ("high", "medium", "low"):
        idea["confidence"] = "low"
    return idea


def _extract_ollama(text):
    """Local, free extraction via an Ollama model (JSON mode)."""
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=180, json={
            "model": OLLAMA_MODEL, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text[:8000]},
            ],
        })
        content = r.json().get("message", {}).get("content", "")
        m = re.search(r"\{.*\}", content, re.S)
        return _validate(json.loads(m.group(0))) if m else None
    except Exception as e:
        log(f"  Ollama extract error: {str(e)[:80]}")
        return None


def _extract_claude(text, client):
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=700, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}])
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        return _validate(json.loads(m.group(0))) if m else None
    except Exception as e:
        log(f"  Claude extract error: {str(e)[:80]}")
        return None


def extract_idea(text, client=None):
    """Extract a structured idea from article text using the configured backend."""
    if not text or len(text) < 200:
        return None
    if EXTRACTOR == "claude":
        return _extract_claude(text, client)
    return _extract_ollama(text)


# ── dedup ──────────────────────────────────────────────────────────────────────
def find_fuzzy_duplicate(db, brand, campaign, existing):
    """Return an existing idea id if brand+campaign closely matches one."""
    key = f"{brand or ''} {campaign or ''}".strip().lower()
    if not key:
        return None
    for eid, ekey in existing:
        if fuzz.token_set_ratio(key, ekey) >= FUZZY_THRESHOLD:
            return eid
    return None


def run_scrape(verbose=True):
    client = None
    if EXTRACTOR == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log("⚠ ANTHROPIC_API_KEY not set — cannot extract ideas. Aborting.")
            return {"added": 0, "error": "no ANTHROPIC_API_KEY"}
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    else:  # ollama
        try:
            tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=8).json().get("models", [])
            names = [m.get("name", "") for m in tags]
            if not any(OLLAMA_MODEL.split(":")[0] in n for n in names):
                log(f"⚠ Ollama model '{OLLAMA_MODEL}' not found (have: {names or 'none'}). "
                    f"Run: ollama pull {OLLAMA_MODEL}. Aborting.")
                return {"added": 0, "error": "ollama model missing"}
        except Exception as e:
            log(f"⚠ Ollama not reachable at {OLLAMA_URL} ({str(e)[:50]}). Aborting.")
            return {"added": 0, "error": "ollama unreachable"}
        log(f"using Ollama model: {OLLAMA_MODEL}")

    import firestore_sync
    if not firestore_sync.is_enabled():
        log("⚠ Firestore not configured — aborting (nothing to write to).")
        return {"added": 0, "error": "no Firestore"}
    db = firestore_sync.get_client()

    # existing ideas: url-ids (exact dedup) + (id, brand+campaign) for fuzzy
    existing_urls = set()
    existing_keys = []
    for doc in db.collection("marketing_ideas").stream():
        existing_urls.add(doc.id)
        d = doc.to_dict()
        existing_keys.append((doc.id, f"{d.get('brand','')} {d.get('campaign_name','')}".strip().lower()))
    log(f"bank has {len(existing_urls)} ideas already")

    added = 0
    for src in SOURCES:
        feed_url = src["feed_url"] or discover_feed(src["home"])
        if not feed_url:
            log(f"{src['name']}: לא נמצא RSS, נדרשת בדיקה ידנית")
            continue
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            log(f"{src['name']}: feed parse error {str(e)[:50]}")
            continue
        entries = feed.entries[:MAX_PER_SOURCE]
        log(f"{src['name']}: {len(feed.entries)} items, checking newest {len(entries)}")
        for e in entries:
            url = e.get("link")
            if not url:
                continue
            doc_id = _id_for_url(url)
            if doc_id in existing_urls:
                continue  # level-1 dedup: exact URL
            text = fetch_article_text(url)
            idea = extract_idea(text, client)
            if not idea:
                continue
            dup_of = find_fuzzy_duplicate(db, idea.get("brand"), idea.get("campaign_name"), existing_keys)
            rec = {
                "date_collected": datetime.now(timezone.utc).isoformat(),
                "source_name": src["name"],
                "source_url": url,
                "published_date": e.get("published", ""),
                "brand": idea.get("brand"),
                "campaign_name": idea.get("campaign_name"),
                "category": idea.get("category"),
                "summary": idea.get("summary"),
                "evidence_of_success": idea.get("evidence_of_success"),
                "confidence": idea.get("confidence", "low"),
                "possible_duplicate_of": dup_of,
                "is_manual": False,
                "tags": "",
            }
            db.collection("marketing_ideas").document(doc_id).set(rec)
            existing_urls.add(doc_id)
            existing_keys.append((doc_id, f"{idea.get('brand','')} {idea.get('campaign_name','')}".strip().lower()))
            added += 1
            log(f"  + {idea.get('brand')} — {idea.get('campaign_name')} ({idea.get('confidence')})"
                + (f" [dup? #{dup_of}]" if dup_of else ""))
            time.sleep(1)   # gentle pace
        time.sleep(2)       # gentle pace between sources

    log(f"DONE — added {added} new idea(s)")
    return {"added": added, "log": _log_lines}


if __name__ == "__main__":
    run_scrape()
