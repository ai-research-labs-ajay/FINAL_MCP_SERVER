"""
48-Hour News Aggregator Tool
Fetches latest news from multiple RSS sources including Reuters and X/Twitter
official accounts, scores impact, and returns structured results.

Twitter/X Strategy (since Twitter killed RSS in 2023):
  1. Nitter RSS mirrors — multiple mirrors tried in sequence
  2. Google News site:x.com proxy — catches viral/trending tweets
  3. 30+ official accounts tracked for market-moving tweets

Reuters Strategy (since Reuters killed public RSS):
  1. Google News "source:Reuters" proxy — most reliable
  2. Reuters website direct scraping as fallback
"""

import re
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, quote_plus

from bs4 import BeautifulSoup

from mcp_webscraper.utils.fetcher import fetch_static
from mcp_webscraper.utils.parser import extract_clean_text

logger = logging.getLogger("mcp-webscraper.news")


# ══════════════════════════════════════════════════════════════════════
#  TWITTER/X OFFICIAL ACCOUNTS TO TRACK
# ══════════════════════════════════════════════════════════════════════
TWITTER_ACCOUNTS = {
    # ── Indian Government & Policy ──
    "narendramodi": "PM Narendra Modi",
    "PMOIndia": "PM Office India",
    "nsitharaman": "FM Nirmala Sitharaman",
    "nsitharamanoffc": "FM Official",
    "FinMinIndia": "Finance Ministry India",

    # ── Indian Regulators ──
    "RBI": "Reserve Bank of India",
    "SEBI_updates": "SEBI",
    "DasShaktikanta": "RBI Governor",
    "NSEIndia": "NSE India",
    "BSEIndia": "BSE India",

    # ── Indian Market Leaders ──
    "anandmahindra": "Anand Mahindra",
    "Nithin0dha": "Nithin Kamath (Zerodha)",
    "RadhikaGupta29": "Radhika Gupta (Edelweiss)",
    "udaykotak": "Uday Kotak",
    "Iamsamirarora": "Samir Arora (Helios)",

    # ── Indian Financial Media ──
    "moneycontrolcom": "Moneycontrol",
    "ETMarkets": "ET Markets",
    "CNBCTV18Live": "CNBC TV18",
    "livemint": "LiveMint",

    # ── US Government & Policy ──
    "realDonaldTrump": "Donald Trump",
    "POTUS": "President of US",
    "whitehouse": "White House",
    "SecScottBessent": "US Treasury Secretary",
    "USTreasury": "US Treasury",

    # ── US Regulators & Agencies ──
    "federalreserve": "Federal Reserve",
    "SEC_News": "SEC",
    "EconAtState": "US Economic Bureau",
    "CommerceGov": "US Commerce Dept",
    "BEA_News": "Bureau of Economic Analysis",

    # ── Russia (geopolitical impact) ──
    "ru_minfin": "Russia Finance Ministry",
    "KremlinRussia_E": "Kremlin (English)",
    "KremlinRussia": "Kremlin (Russian)",
    "mfa_russia": "Russia Foreign Ministry",
    "GovernmentRF": "Russian Government",
    "RusEmbUSA": "Russian Embassy US",
    "mod_russia": "Russia Defense Ministry",
}

# Nitter mirrors to try (rotates if one is down)
NITTER_MIRRORS = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.net",
    "https://nitter.cz",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]


# ══════════════════════════════════════════════════════════════════════
#  RSS NEWS FEEDS
# ══════════════════════════════════════════════════════════════════════
NEWS_FEEDS = {
    "india_markets": [
        ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "Economic Times Markets"),
        ("https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", "ET Stocks"),
        ("https://www.moneycontrol.com/rss/latestnews.xml", "Moneycontrol"),
        ("https://economictimes.indiatimes.com/rssfeedstopstories.cms", "ET Top Stories"),
        ("https://www.livemint.com/rss/markets", "LiveMint Markets"),
    ],
    "global_markets": [
        ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US", "Yahoo Finance US"),
        ("https://feeds.bbci.co.uk/news/business/rss.xml", "BBC Business"),
        ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NYT Business"),
        ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC Markets"),
    ],
    "reuters": [
        # Reuters killed public RSS — use Google News as proxy
        ("https://news.google.com/rss/search?q=source:Reuters+markets+OR+stocks+OR+economy&hl=en&gl=US&ceid=US:en", "Reuters via Google News"),
        ("https://news.google.com/rss/search?q=source:Reuters+india+OR+nifty+OR+sensex+OR+rupee&hl=en-IN&gl=IN&ceid=IN:en", "Reuters India via Google"),
        ("https://news.google.com/rss/search?q=source:Reuters+crude+OR+oil+OR+war+OR+fed&hl=en&gl=US&ceid=US:en", "Reuters Macro via Google"),
    ],
    "twitter": [
        # Google News catches viral tweets
        ("https://news.google.com/rss/search?q=site:x.com+stock+market+crash+OR+surge+OR+breaking&hl=en&gl=US&ceid=US:en", "X/Twitter Breaking Markets"),
        ("https://news.google.com/rss/search?q=site:x.com+nifty+OR+sensex+OR+rupee+OR+RBI&hl=en-IN&gl=IN&ceid=IN:en", "X/Twitter India Markets"),
        ("https://news.google.com/rss/search?q=site:x.com+fed+OR+trump+OR+tariff+OR+war+finance&hl=en&gl=US&ceid=US:en", "X/Twitter US Policy"),
    ],
    "crypto": [
        ("https://cointelegraph.com/rss", "CoinTelegraph"),
        ("https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+crypto&hl=en&gl=US&ceid=US:en", "Crypto via Google News"),
    ],
    "technology": [
        ("https://feeds.feedburner.com/TechCrunch/", "TechCrunch"),
        ("https://www.theverge.com/rss/index.xml", "The Verge"),
        ("https://news.google.com/rss/search?q=technology+AI+startup&hl=en&gl=US&ceid=US:en", "Tech via Google News"),
    ],
}


# ══════════════════════════════════════════════════════════════════════
#  IMPACT SCORING
# ══════════════════════════════════════════════════════════════════════
HIGH_IMPACT_KEYWORDS = {
    # Market-moving
    "crash": 4, "surge": 3, "record": 3, "plunge": 4, "soar": 3,
    "bloodbath": 5, "rally": 2, "breakout": 3, "collapse": 4,
    "all-time": 3, "worst": 3, "best": 2, "historic": 3,
    "skyrocket": 3, "tumble": 3, "meltdown": 4, "freefall": 4,
    "wipe": 3, "erased": 3, "trillion": 3,
    # Geopolitical
    "war": 4, "crisis": 3, "sanction": 3, "tariff": 3, "ban": 2,
    "emergency": 3, "default": 4, "invasion": 4, "missile": 3,
    "ceasefire": 3, "nuclear": 4, "conflict": 2, "strike": 2,
    # Central banks / Macro
    "rbi": 2, "fed": 2, "rate cut": 3, "rate hike": 3,
    "inflation": 2, "recession": 3, "gdp": 2, "cpi": 2,
    "unemployment": 2, "stimulus": 3, "quantitative": 2,
    "hawkish": 2, "dovish": 2, "tightening": 2,
    # India specific
    "nifty": 1, "sensex": 1, "rupee": 2, "crude": 2,
    "fii": 2, "dii": 1, "ipo": 2, "sebi": 2,
    "adani": 2, "reliance": 1, "tata": 1,
    # Big numbers
    "billion": 2, "lakh crore": 3,
    # Crypto
    "bitcoin": 1, "ethereum": 1, "crypto": 1, "halving": 2,
}


def _score_impact(title: str, summary: str) -> tuple[int, str, list[str]]:
    """Score an article's market impact."""
    text = (title + " " + summary).lower()
    score = 0
    matched = []

    for kw, weight in HIGH_IMPACT_KEYWORDS.items():
        if kw in text:
            score += weight
            matched.append(kw)

    # Extra weight for big numbers
    big_nums = re.findall(r'[\$\u20b9]\s*[\d,.]+\s*(billion|trillion|crore|lakh)', text)
    score += len(big_nums) * 3
    pct = re.findall(r'[\d.]+\s*%', text)
    score += len(pct) * 1

    if score >= 10:
        level = "CRITICAL"
    elif score >= 6:
        level = "HIGH"
    elif score >= 3:
        level = "MEDIUM"
    else:
        level = "LOW"

    return score, level, matched


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse various RSS date formats."""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%d %b %Y %H:%M:%S %z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _is_within_hours(pub_time: Optional[datetime], hours: int = 48) -> bool:
    """Check if a datetime is within the last N hours."""
    if not pub_time:
        return True
    try:
        now = datetime.now(pub_time.tzinfo) if pub_time.tzinfo else datetime.now()
        diff = now - pub_time
        return timedelta(0) <= diff <= timedelta(hours=hours)
    except Exception:
        return True


def _extract_google_news_real_url(url: str) -> str:
    """Extract real URL from Google News redirect."""
    if "news.google.com" in url and "articles/" in url:
        # Google News URLs are base64 encoded — can't easily decode
        # Return as-is, the redirect will work in browser
        return url
    if "news.google.com" in url and "url=" in url:
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "url" in qs:
                return qs["url"][0]
        except Exception:
            pass
    return url


# ══════════════════════════════════════════════════════════════════════
#  RSS FEED FETCHER
# ══════════════════════════════════════════════════════════════════════
async def fetch_rss_feed(url: str, source_name: str, hours: int = 48) -> list[dict]:
    """Fetch and parse a single RSS feed."""
    result = await fetch_static(url, timeout=15)
    if result.error:
        logger.warning(f"Failed to fetch {source_name}: {result.error}")
        return []

    if result.status_code not in (200, 301, 302, 0):
        logger.warning(f"Bad status {result.status_code} from {source_name}")
        return []

    html = result.html
    if not html or len(html.strip()) < 50:
        return []

    # Parse RSS/Atom XML
    try:
        soup = BeautifulSoup(html, "lxml-xml")
        items = soup.find_all("item")
        if not items:
            items = soup.find_all("entry")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
            items = soup.find_all("item")
            if not items:
                items = soup.find_all("entry")
        except Exception as e:
            logger.warning(f"Parse failed for {source_name}: {e}")
            return []

    if not items:
        return []

    articles = []
    for item in items[:25]:
        # Title
        title_tag = item.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title or len(title) < 10:
            continue

        # Link
        link = ""
        link_tag = item.find("link")
        if link_tag:
            link = link_tag.get("href", "") or link_tag.get_text(strip=True) or ""
        if not link:
            guid_tag = item.find("guid")
            if guid_tag:
                guid_text = guid_tag.get_text(strip=True)
                if guid_text.startswith("http"):
                    link = guid_text

        link = _extract_google_news_real_url(link)

        # Date
        date_tag = (
            item.find("pubDate") or item.find("published")
            or item.find("updated") or item.find("dc:date")
        )
        pub_date = date_tag.get_text(strip=True) if date_tag else ""
        parsed_date = _parse_date(pub_date)

        if not _is_within_hours(parsed_date, hours):
            continue

        # Summary
        summary = ""
        desc_tag = item.find("description") or item.find("summary") or item.find("content")
        if desc_tag:
            raw = desc_tag.get_text() or ""
            summary = BeautifulSoup(raw, "html.parser").get_text(strip=True)[:500]

        # Source (some feeds include <source> tag)
        src_tag = item.find("source")
        real_source = src_tag.get_text(strip=True) if src_tag else source_name

        # Score
        score, level, keywords = _score_impact(title, summary)

        articles.append({
            "source": real_source,
            "feed": source_name,
            "title": title,
            "link": link,
            "published": pub_date,
            "summary": summary[:300],
            "impact_score": score,
            "impact_level": level,
            "impact_keywords": keywords,
        })

    logger.info(f"Fetched {len(articles)} articles from {source_name}")
    return articles


# ══════════════════════════════════════════════════════════════════════
#  TWITTER/X FETCHER — Nitter Mirrors + Google News
# ══════════════════════════════════════════════════════════════════════
async def _fetch_twitter_account_nitter(
    handle: str, display_name: str, nitter_host: str, hours: int = 48
) -> list[dict]:
    """Fetch tweets from a single account via a Nitter mirror."""
    rss_url = f"{nitter_host}/{handle}/rss"
    result = await fetch_static(rss_url, timeout=10)

    if result.error or not result.html:
        return []
    if "<item" not in result.html.lower() and "<entry" not in result.html.lower():
        return []

    try:
        soup = BeautifulSoup(result.html, "lxml-xml")
        items = soup.find_all("item") or soup.find_all("entry")
    except Exception:
        return []

    tweets = []
    for item in items[:10]:
        title_tag = item.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title or len(title) < 15:
            continue

        # Clean up title (Nitter sometimes prepends "RT by @...")
        if title.startswith("RT by"):
            title = title.split(":", 1)[-1].strip() if ":" in title else title

        link_tag = item.find("link")
        link = link_tag.get_text(strip=True) if link_tag else ""
        # Convert Nitter link to X.com link
        if nitter_host in link:
            link = link.replace(nitter_host, "https://x.com")

        pub_tag = item.find("pubDate") or item.find("published")
        pub_date = pub_tag.get_text(strip=True) if pub_tag else ""
        parsed_date = _parse_date(pub_date)

        if not _is_within_hours(parsed_date, hours):
            continue

        # Description (tweet body)
        desc_tag = item.find("description") or item.find("content")
        desc = ""
        if desc_tag:
            desc = BeautifulSoup(desc_tag.get_text() or "", "html.parser").get_text(strip=True)[:300]

        score, level, keywords = _score_impact(title, desc)

        tweets.append({
            "source": f"X/@{handle} ({display_name})",
            "feed": f"Nitter: {nitter_host.split('//')[1]}",
            "title": title[:250],
            "link": link,
            "published": pub_date,
            "summary": desc[:300] if desc != title else "",
            "impact_score": score,
            "impact_level": level,
            "impact_keywords": keywords,
        })

    return tweets


async def _fetch_all_twitter_accounts(hours: int = 48) -> list[dict]:
    """
    Fetch tweets from ALL tracked official accounts via Nitter mirrors.
    Tries each mirror until one works, then fetches all accounts from it.
    """
    all_tweets = []

    # Step 1: Find a working Nitter mirror
    working_mirror = None
    for mirror in NITTER_MIRRORS:
        test_result = await fetch_static(f"{mirror}/narendramodi/rss", timeout=8)
        if test_result.html and "<item" in test_result.html.lower():
            working_mirror = mirror
            logger.info(f"Using Nitter mirror: {mirror}")
            break
        else:
            logger.debug(f"Nitter mirror down: {mirror}")

    # Step 2: If a mirror works, fetch all accounts concurrently
    if working_mirror:
        tasks = [
            _fetch_twitter_account_nitter(handle, name, working_mirror, hours)
            for handle, name in TWITTER_ACCOUNTS.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                all_tweets.extend(r)

        logger.info(f"Fetched {len(all_tweets)} tweets via Nitter ({working_mirror})")
    else:
        logger.warning("No Nitter mirrors available — falling back to Google News only")

    # Step 3: Google News fallback — always run to catch viral tweets
    google_queries = [
        # Indian official accounts
        "site:x.com (narendramodi OR nsitharaman OR RBI OR SEBI_updates OR NSEIndia) market",
        # Global finance accounts
        "site:x.com (realDonaldTrump OR federalreserve OR SecScottBessent) economy OR market OR tariff",
        # Indian market influencers
        "site:x.com (Nithin0dha OR anandmahindra OR udaykotak OR ETMarkets) stock OR market",
        # Russia geopolitical
        "site:x.com (KremlinRussia_E OR mfa_russia OR mod_russia) war OR sanction OR oil",
    ]

    google_tasks = []
    for q in google_queries:
        encoded = quote_plus(q)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"
        google_tasks.append(fetch_rss_feed(url, f"X/Twitter via Google News", hours))

    google_results = await asyncio.gather(*google_tasks, return_exceptions=True)
    for r in google_results:
        if isinstance(r, list):
            all_tweets.extend(r)

    return all_tweets


# ══════════════════════════════════════════════════════════════════════
#  REUTERS FETCHER — Google News proxy + Direct Scrape
# ══════════════════════════════════════════════════════════════════════
async def _scrape_reuters_direct() -> list[dict]:
    """Scrape Reuters website directly as fallback."""
    articles = []
    urls = [
        "https://www.reuters.com/markets/",
        "https://www.reuters.com/world/",
        "https://www.reuters.com/business/",
    ]

    for page_url in urls:
        result = await fetch_static(page_url, timeout=15)
        if result.error or not result.html or len(result.html) < 500:
            continue

        soup = BeautifulSoup(result.html, "lxml")
        section = page_url.split(".com/")[1].rstrip("/")

        # Reuters article links contain date patterns like /2026/03/30/
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            text = a_tag.get_text(strip=True)

            if not text or len(text) < 25 or len(text) > 300:
                continue
            if not href.startswith("/"):
                continue
            if any(skip in href for skip in ["/video/", "/pictures/", "/authors/", "/about/", "/graphics/"]):
                continue

            full_url = urljoin("https://www.reuters.com", href)
            score, level, keywords = _score_impact(text, "")

            articles.append({
                "source": f"Reuters ({section})",
                "feed": "Reuters Website Scrape",
                "title": text,
                "link": full_url,
                "published": "",
                "summary": "",
                "impact_score": score,
                "impact_level": level,
                "impact_keywords": keywords,
            })

    # Deduplicate
    seen = set()
    unique = []
    for a in articles:
        key = a["title"].lower()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    logger.info(f"Scraped {len(unique)} articles from Reuters website")
    return unique[:30]


# ══════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════
async def fetch_news(
    category: str = "india_markets",
    hours: int = 48,
    min_impact: str = "LOW",
) -> dict:
    """
    Fetch news from RSS feeds for a given category.

    Args:
        category: One of 'india_markets', 'global_markets', 'reuters', 'twitter',
                  'crypto', 'technology', or 'all'.
        hours: Time window in hours (default 48).
        min_impact: Minimum impact level: 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'.

    Returns:
        Dict with articles sorted by impact score.
    """
    all_categories = list(NEWS_FEEDS.keys())

    # Validate category
    if category not in (*all_categories, "all"):
        return {
            "error": f"Unknown category '{category}'. Available: {', '.join(all_categories)}, or 'all'.",
        }

    # Determine which feeds to fetch
    if category == "all":
        feeds = []
        for cat_feeds in NEWS_FEEDS.values():
            feeds.extend(cat_feeds)
    else:
        feeds = NEWS_FEEDS[category]

    # Launch all tasks concurrently
    tasks = [fetch_rss_feed(url, name, hours) for url, name in feeds]

    # Add special scrapers for Reuters and Twitter
    include_reuters = category in ("reuters", "all")
    include_twitter = category in ("twitter", "all")

    if include_reuters:
        tasks.append(_scrape_reuters_direct())
    if include_twitter:
        tasks.append(_fetch_all_twitter_accounts(hours))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results
    all_articles = []
    errors = []
    for r in results:
        if isinstance(r, list):
            all_articles.extend(r)
        elif isinstance(r, Exception):
            errors.append(str(r))

    # Deduplicate by title
    seen = set()
    unique = []
    for a in all_articles:
        key = a["title"].lower()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    # Filter by minimum impact
    impact_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    min_val = impact_order.get(min_impact.upper(), 0)
    filtered = [a for a in unique if impact_order.get(a["impact_level"], 0) >= min_val]

    # Sort by impact score descending
    filtered.sort(key=lambda x: x["impact_score"], reverse=True)

    # Stats
    critical = sum(1 for a in filtered if a["impact_level"] == "CRITICAL")
    high = sum(1 for a in filtered if a["impact_level"] == "HIGH")
    medium = sum(1 for a in filtered if a["impact_level"] == "MEDIUM")
    low = sum(1 for a in filtered if a["impact_level"] == "LOW")

    # Build sources list
    sources = [name for _, name in feeds]
    if include_reuters:
        sources.append("Reuters Direct Scrape")
    if include_twitter:
        sources.append(f"X/Twitter ({len(TWITTER_ACCOUNTS)} official accounts via Nitter)")
        sources.append("X/Twitter via Google News (4 search queries)")

    return {
        "category": category,
        "time_window_hours": hours,
        "min_impact_filter": min_impact,
        "timestamp": datetime.now().isoformat(),
        "total_articles": len(filtered),
        "impact_summary": {
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
        },
        "twitter_accounts_tracked": list(TWITTER_ACCOUNTS.keys()) if category in ("twitter", "all") else None,
        "articles": filtered,
        "sources_checked": sources,
        "errors": errors if errors else None,
    }
