"""
Press monitoring scraper — "מעקב עיתונות".

Scans Israeli news sites daily for BUSINESS news about restaurants and home
food delivery (chains, openings/closures, franchising, funding, M&A, revenue,
labor disputes) — NOT general news, and NOT recipes/reviews/lifestyle pieces
about food. Each run collects articles published in the last 24h that pass
BOTH filters below, with a short (already-Hebrew) summary and a link. Stored
per day in Firestore (`press_daily/{date}`); the dashboard shows today's
table on top and a cumulative archive (built from all daily docs) below.

Fixed sources (RSS where available):
  globes    -> the "נתח שוק וצרכנות" (market share / consumerism) section RSS —
               retail chains, food brands, consumer business
  mako      -> mako's dedicated restaurants section RSS (Ynet-group sister
               site; Ynet's own feed is general politics/economy, so this
               replaces it)
  themarker -> the "tm-consumer" (consumer/retail) section RSS
  ice       -> general RSS feed — ice.co.il has no food/business-specific
               section feed (checked: /rss section pages have no RSS
               autodiscovery, and guessed path variants all fall back to the
               same generic mix), so this one relies entirely on the filters
               below.
  calcalist -> no public RSS (blocked); covered via Bing News site-restricted
               search per topic keyword instead.

(Haaretz's "אוכל"/Food section was tried here previously — dropped: it's
pure recipes/cooking content, which by definition never has a business
angle, so every article from it was going to be rejected by the business
filter anyway.)

Every article must pass TWO independent filters:
  1. _is_relevant() — is it about restaurants/food-delivery/pizza at all?
  2. _is_business() — does it actually carry a BUSINESS angle (chain/branch,
     franchising, ownership, funding, M&A, revenue, closures, labor)? This
     is what excludes recipes, dish reviews, and "we tasted everything"
     lifestyle pieces even from sources that are otherwise on-topic.

Note: the general/homepage feeds for globes, ynet, and themarker used to be
wired in here directly — they're almost entirely stock-market/politics/crime
news, so on days where a headline happened to mention a topic keyword in
passing, unrelated political/financial articles leaked into the dashboard.
Swapping in each site's actual food/consumer/restaurant section (or, for
Ynet, its sister site's restaurants feed) fixes that at the source; the
keyword filters are a second layer, not the only one.

Users can add more sites from the dashboard (Firestore `press_sources`); at
scrape time we auto-discover each one's RSS feed the same way marketing_scraper
does, and fold it into the same two filters.
"""

import re, sys, io, html, time
from datetime import datetime

import requests
import feedparser

from multi_scraper import UA  # importing this also configures UTF-8 stdout/stderr on Windows
from marketing_scraper import discover_feed  # reuse the same feed-discovery logic

WINDOW_HOURS = 24

FIXED_SOURCES = [
    {"key": "globes", "name": "גלובס · נתח שוק וצרכנות", "mode": "rss",
     "feed_url": "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=821"},
    {"key": "mako", "name": "מאקו · מסעדות", "mode": "rss", "restaurant_dedicated": True,
     "feed_url": "https://rcs.mako.co.il/rss/food-restaurants.xml"},
    {"key": "themarker", "name": "דה מרקר · צרכנות", "mode": "rss",
     "feed_url": "https://www.themarker.com/srv/tm-consumer"},
    {"key": "ice", "name": "Ice", "mode": "rss", "feed_url": "https://www.ice.co.il/rss"},
    {"key": "calcalist", "name": "כלכליסט", "mode": "search", "domain": "calcalist.co.il"},
]

# Topic filter: restaurants, home food delivery, pizza (emphasis).
# Split into single WORDS (matched via tokenize + prefix-strip, below) and
# multi-word PHRASES (matched via plain substring — a 2-3 word Hebrew phrase
# is specific enough that substring search won't false-positive).
KW_PIZZA_WORDS = {"פיצה", "פיצריה", "פיצריות", "פיצות", "פיצת", "pizza"}
KW_GENERAL_WORDS = {"מסעדה", "מסעדות", "מסעדנות", "מסעדת", "וולט", "wolt", "קייטרינג",
                    "פודטק", "10ביס", "10bis"}
KW_GENERAL_PHRASES = ["רשת מסעדות", "רשתות מזון", "משלוחי מזון", "משלוח מזון",
                      "משלוח אוכל", "משלוחי אוכל", "שליחי מזון", "תן ביס",
                      "אוכל מהיר", "מזון מהיר"]

# Business-dimension filter: an article must ALSO carry one of these signals
# to qualify — otherwise it's a recipe, a dish review, or a "we tasted
# everything" lifestyle piece, none of which belong in a BUSINESS monitor.
BIZ_WORDS = {"רשת", "רשתות", "זכיינות", "זכיין", "זכיינים", "סניף", "סניפים",
             "בעלים", "יזם", "יזמים", "משקיע", "משקיעים", "השקעה", "השקעות",
             "רכישה", "רכש", "נרכש", "נרכשה", "מיזוג", "מחזור", "הכנסות",
             "רווח", "רווחים", "הפסד", "הפסדים", "קריסה", "קרס", "קרסה",
             "עובדים", "פיטורים", "פיטורי", "הרחבה", "התרחבות", "התפשטות",
             "קמעונאות", "קמעונאי", "קמעונאים", "מכירות", "הנפקה", "גיוס",
             "תאגיד", "חברה", "חברת", "מנכ", "פרנצ'ייז", "פרנצ׳ייז"}
BIZ_PHRASES = ["פשיטת רגל", "גיוס הון", "הון סיכון", "דוחות כספיים", "דוח כספי",
               "סגר את שעריו", "סגרה את שעריה", "פתח סניף", "פתחה סניף",
               "פתיחת סניף", "סגר סניף", "סגרה סניף", "סגירת סניף",
               "ועד עובדים", "סכסוך עבודה", "מיליון שקל", "מיליון ש\"ח",
               "מיליוני שקלים"]

# Naive substring search is unsafe in Hebrew: "הקפיצה" (jumped) contains the
# literal substring "פיצה" (pizza). Instead we tokenize into whole words and
# strip the standard one-letter prefixes (ו/ה/ב/ל/מ/ש/כ — "במסעדה" = "in the
# restaurant") before comparing, the same approach used by the dashboard's
# Hebrew smart-search stemmer.
_HE_PFX = set("והבלמשכ")


def _prefix_variants(w):
    """All of w with 0, 1, or 2 leading Hebrew prefix letters stripped — every
    intermediate form is kept (not just the final one), so e.g. 'במסעדה'
    yields both 'מסעדה' (1 strip) and 'סעדה' (2 strips), not only the latter."""
    variants = {w}
    c = w
    for _ in range(2):
        if len(c) > 3 and c[0] in _HE_PFX:
            c = c[1:]
            variants.add(c)
        else:
            break
    return variants


def _tokens(text):
    words = re.findall(r"[א-ת]+|[a-zA-Z0-9]+", text or "")
    out = set()
    for w in words:
        out |= _prefix_variants(w.lower())
    return out


# Search queries used for sources with no direct RSS (Bing News, site-restricted).
SEARCH_QUERIES = ["פיצה", "מסעדות", "משלוחי מזון", "וולט משלוחים", "קייטרינג"]


def _is_pizza(text):
    return bool(_tokens(text) & KW_PIZZA_WORDS)


def _is_relevant(text):
    if _is_pizza(text):
        return True
    if _tokens(text) & KW_GENERAL_WORDS:
        return True
    return any(ph in (text or "") for ph in KW_GENERAL_PHRASES)


def _is_business(text):
    if _tokens(text) & BIZ_WORDS:
        return True
    return any(ph in (text or "") for ph in BIZ_PHRASES)


def _clean(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _news_feed(query):
    """Bing News search RSS for a query, restricted to a domain."""
    return "https://www.bing.com/news/search?q=" + requests.utils.quote(query) + "&format=rss&setlang=he-il&cc=IL"


def fetch_rss_entries(feed_url, verbose=True):
    """Parse a feed URL into a flat list of {title, desc, link, published, age_h}."""
    now = time.time()
    out = []
    try:
        feed = feedparser.parse(feed_url, request_headers={"User-Agent": UA})
    except Exception as e:
        if verbose:
            print(f"    feed error ({feed_url[:60]}): {str(e)[:60]}")
        return out
    for e in feed.entries:
        title = _clean(e.get("title"))
        link = e.get("link") or ""
        if not title or not link:
            continue
        pub = e.get("published_parsed") or e.get("updated_parsed")
        age_h = (now - time.mktime(pub)) / 3600 if pub else 1e9
        out.append({"title": title, "desc": _clean(e.get("summary") or e.get("description")),
                    "link": link, "published": e.get("published", ""), "age_h": age_h})
    return out


def collect_source(src, verbose=True):
    """Return relevant, last-24h entries for one source (fixed or user-added)."""
    if src["mode"] == "search":
        seen, pool = set(), []
        for q in SEARCH_QUERIES:
            feed_url = _news_feed(f'site:{src["domain"]} {q}')
            for e in fetch_rss_entries(feed_url, verbose=False):
                if e["link"] in seen:
                    continue
                seen.add(e["link"])
                pool.append(e)
    else:
        pool = fetch_rss_entries(src["feed_url"], verbose=verbose)

    out = []
    for e in pool:
        if e["age_h"] > WINDOW_HOURS:
            continue
        hay = f"{e['title']} {e['desc']}"
        # A feed whose entire section IS restaurants (mako) doesn't need the
        # generic topic check — e.g. a sushi-bar opening piece never says the
        # literal word "מסעדה". But EVERY source, including this one, must
        # still pass the business-angle check: that's what excludes recipes,
        # dish reviews, and "we tasted everything" lifestyle pieces.
        if not src.get("restaurant_dedicated") and not _is_relevant(hay):
            continue
        if not _is_business(hay):
            continue
        out.append({
            "source": src["key"], "source_name": src["name"],
            "title": e["title"], "summary": e["desc"][:700],
            "url": e["link"], "published": e["published"],
            "is_pizza": _is_pizza(hay),
        })
    if verbose:
        print(f"    {src['name']}: {len(pool)} scanned, {len(out)} on-topic in last {WINDOW_HOURS}h")
    return out


def load_user_sources(db, verbose=True):
    """User-added sites (Firestore `press_sources`) — auto-discover their feed."""
    sources = []
    try:
        for doc in db.collection("press_sources").stream():
            s = doc.to_dict()
            name, url = s.get("name", "מקור ידני"), s.get("url", "")
            if not url:
                continue
            feed_url = url if fetch_rss_entries(url, verbose=False) else discover_feed(url)
            if feed_url:
                sources.append({"key": doc.id, "name": name, "mode": "rss", "feed_url": feed_url})
                if verbose:
                    print(f"    user source: {name} ✓")
            elif verbose:
                print(f"    user source: {name} — no RSS found, skipped")
    except Exception as e:
        if verbose:
            print(f"  user sources load error: {str(e)[:60]}")
    return sources


def run_scrape(verbose=True):
    if verbose:
        print(f"  Press monitoring — scanning sources (last {WINDOW_HOURS}h)...")

    import firestore_sync
    enabled = firestore_sync.is_enabled()
    db = firestore_sync.get_client() if enabled else None

    sources = list(FIXED_SOURCES)
    if enabled:
        sources += load_user_sources(db, verbose=verbose)

    articles = []
    for src in sources:
        try:
            articles += collect_source(src, verbose=verbose)
        except Exception as e:
            if verbose:
                print(f"    {src.get('name')}: error {str(e)[:80]}")

    articles.sort(key=lambda a: a.get("published", ""), reverse=True)
    date = datetime.now().strftime("%Y-%m-%d")
    entry = {"date": date, "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "count": len(articles), "articles": articles}
    if verbose:
        print(f"  Total on-topic articles today: {len(articles)}")

    if enabled:
        db.collection("press_daily").document(date).set(entry)
        if verbose:
            print("  Synced press monitoring → Firestore ✓")
    elif verbose:
        print("  Firestore not configured — skipped push.")

    if verbose:
        print("Done.")
    return entry


if __name__ == "__main__":
    run_scrape()
