"""
48-Hour News Aggregator Tool
Fetches latest news from multiple RSS sources including Reuters and X/Twitter,
scores impact, and returns structured results.
"""

import re
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from mcp_webscraper.utils.fetcher import fetch_static
from mcp_webscraper.utils.parser import extract_clean_text

logger = logging.getLogger("mcp-webscraper.news")

# ── RSS Sources ───────────────────────────────────────────────────────
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
        ("https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best", "Reuters Best"),
        ("https://news.google.com/rss/search?q=reuters+markets&hl=en-IN&gl=IN&ceid=IN:en", "Reuters via Google News"),
        ("https://news.google.com/rss/search?q=reuters+stocks&hl=en-IN&gl=IN&ceid=IN:en", "Reuters Stocks via Google"),
    ],
    "twitter": [
        # Twitter/X killed RSS in 2023. We use Nitter mirrors + Google News as workarounds
        ("https://news.google.com/rss/search?q=site:x.com+OR+site:twitter.com+stock+market&hl=en&gl=US&ceid=US:en", "X/Twitter via Google News"),
        ("https://news.google.com/rss/search?q=site:x.com+OR+site:twitter.com+breaking+finance&hl=en&gl=US&ceid=US:en", "X/Twitter Finance via Google"),
        # Nitter mirrors (may rotate — we try multiple)
        ("https://nitter.privacydev.net/markets/rss", "Nitter Markets"),
        ("https://nitter.poast.org/markets/rss", "Nitter Markets Alt"),
    ],
    "crypto": [
        ("https://cointelegraph.com/rss", "CoinTelegraph"),
        ("https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+crypto&hl=en&gl=US&ceid=US:en", "Crypto via Google News"),
    ],
    "technology": [
        ("https://feeds.feedburner.com/TechCrunch/", "TechCrunch"),
        ("https://www.theverge.com/rss/index.xml", "The Verge"),
        ("https://news.google.com/rss/search?q=technology+AI&hl=en&gl=US&ceid=US:en", "Tech via Google News"),
    ],
}

# ── Impact Scoring ────────────────────────────────────────────────────
HIGH_IMPACT_KEYWORDS = {
    # Market-moving
    "crash": 4, "surge": 3, "record": 3, "plunge": 4, "soar": 3,
    "bloodbath": 5, "rally": 2, "breakout": 3, "collapse": 4,
    "all-time": 3, "worst": 3, "best": 2, "historic": 3,
    "skyrocket": 3, "tumble": 3, "meltdown": 4, "freefall": 4,
    # Geopolitical
    "war": 4, "crisis": 3, "sanction": 3, "tariff": 3, "ban": 2,
    "emergency": 3, "default": 4, "invasion": 4, "missile": 3,
    "ceasefire": 3, "nuclear": 4, "conflict": 2,
    # Central banks / Macro
    "rbi": 2, "fed": 2, "rate cut": 3, "rate hike": 3,
    "inflation": 2, "recession": 3, "gdp": 2, "cpi": 2,
    "unemployment": 2, "stimulus": 3, "quantitative": 2,
    # India specific
    "nifty": 1, "sensex": 1, "rupee": 2, "crude": 2,
    "fii": 2, "dii": 1, "ipo": 2, "sebi": 2,
    "adani": 2, "reliance": 1, "tata": 1,
    # Big numbers
    "billion": 2, "trillion": 3, "lakh crore": 3,
    # Crypto
    "bitcoin": 1, "ethereum": 1, "crypto": 1, "halving": 2,
}


def _score_impact(title: str, summary: str) -> tuple[int, str, list[str]]:
    """Score an article's market impact. Returns (score, level, matched_keywords)."""
    text = (title + " " + summary).lower()
    score = 0
    matched = []

    for kw, weight in HIGH_IMPACT_KEYWORDS.items():
        if kw in text:
            score += weight
            matched.append(kw)

    # Extra weight for quantified numbers ($X billion, X%)
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
    """Try to parse various RSS date formats."""
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
        return True  # Include if we can't determine the date
    try:
        now = datetime.now(pub_time.tzinfo) if pub_time.tzinfo else datetime.now()
        diff = now - pub_time
        return timedelta(0) <= diff <= timedelta(hours=hours)
    except Exception:
        return True


async def fetch_rss_feed(url: str, source_name: str, hours: int = 48) -> list[dict]:
    """Fetch and parse a single RSS feed. Handles XML, Atom, and Google News formats."""
    result = await fetch_static(url, timeout=15)
    if result.error:
        logger.warning(f"Failed to fetch {source_name}: {result.error}")
        return []

    if result.status_code not in (200, 301, 302, 0):
        logger.warning(f"Bad status {result.status_code} from {source_name}")
        return []

    html = result.html
    if not html or len(html.strip()) < 50:
        logger.warning(f"Empty response from {source_name}")
        return []

    # Try XML parser first, fall back to html.parser
    try:
        soup = BeautifulSoup(html, "lxml-xml")
        items = soup.find_all("item")
        if not items:
            items = soup.find_all("entry")  # Atom feeds
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
        logger.warning(f"No items found in {source_name}")
        return []

    articles = []
    for item in items[:25]:
        # ── Title ──
        title_tag = item.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            continue

        # ── Link (handles RSS <link>, Atom <link href=>, Google News) ──
        link = ""
        link_tag = item.find("link")
        if link_tag:
            link = link_tag.get("href", "") or link_tag.get_text(strip=True) or ""

        # Google News wraps real URL in redirect — extract it
        if "news.google.com" in link and "url=" in link:
            try:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(link)
                qs = parse_qs(parsed.query)
                if "url" in qs:
                    link = qs["url"][0]
            except Exception:
                pass

        # Also check <guid> for link
        if not link:
            guid_tag = item.find("guid")
            if guid_tag:
                guid_text = guid_tag.get_text(strip=True)
                if guid_text.startswith("http"):
                    link = guid_text

        # ── Published Date ──
        date_tag = (
            item.find("pubDate")
            or item.find("published")
            or item.find("updated")
            or item.find("dc:date")
        )
        pub_date = date_tag.get_text(strip=True) if date_tag else ""
        parsed_date = _parse_date(pub_date)

        # Filter by time window
        if not _is_within_hours(parsed_date, hours):
            continue

        # ── Summary / Description ──
        summary = ""
        desc_tag = item.find("description") or item.find("summary") or item.find("content")
        if desc_tag:
            raw_desc = desc_tag.get_text() or ""
            desc_soup = BeautifulSoup(raw_desc, "html.parser")
            summary = desc_soup.get_text(strip=True)[:500]

        # ── Source tag (some feeds include <source>) ──
        src_tag = item.find("source")
        real_source = src_tag.get_text(strip=True) if src_tag else source_name

        # ── Score impact ──
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


async def _scrape_reuters_page() -> list[dict]:
    """
    Scrape Reuters markets page directly as a fallback
    since Reuters killed their public RSS feeds.
    """
    articles = []
    urls_to_try = [
        "https://www.reuters.com/markets/",
        "https://www.reuters.com/business/",
    ]

    for page_url in urls_to_try:
        result = await fetch_static(page_url, timeout=15)
        if result.error or not result.html:
            continue

        soup = BeautifulSoup(result.html, "lxml")

        # Reuters uses data-testid attributes for article cards
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            text = a_tag.get_text(strip=True)

            # Filter: only article links with enough text
            if not text or len(text) < 20:
                continue
            if not href.startswith("/"):
                continue
            if any(skip in href for skip in ["/video/", "/pictures/", "/authors/", "/about/"]):
                continue

            full_url = urljoin("https://www.reuters.com", href)
            score, level, keywords = _score_impact(text, "")

            articles.append({
                "source": "Reuters",
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

    return unique[:20]


async def _scrape_twitter_trends() -> list[dict]:
    """
    Scrape X/Twitter trending finance topics via Nitter mirrors
    or Google News as a fallback. Twitter killed RSS in 2023.
    """
    articles = []

    # Try Nitter mirrors for popular finance accounts
    nitter_hosts = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.net",
    ]

    finance_accounts = [
        "markets", "business", "CNBCnow", "ReutersBiz",
        "Bloomberg", "WSJ", "ETNOWlive",
    ]

    for host in nitter_hosts:
        for account in finance_accounts[:3]:  # Limit to avoid rate limits
            rss_url = f"{host}/{account}/rss"
            result = await fetch_static(rss_url, timeout=10)
            if result.error or not result.html or "<item" not in result.html.lower():
                continue

            try:
                soup = BeautifulSoup(result.html, "lxml-xml")
                items = soup.find_all("item")

                for item in items[:5]:
                    title_tag = item.find("title")
                    title = title_tag.get_text(strip=True) if title_tag else ""
                    if not title or len(title) < 15:
                        continue

                    link_tag = item.find("link")
                    link = link_tag.get_text(strip=True) if link_tag else ""

                    # Convert nitter link back to twitter
                    if host in link:
                        link = link.replace(host, "https://x.com")

                    pub_tag = item.find("pubDate")
                    pub_date = pub_tag.get_text(strip=True) if pub_tag else ""

                    score, level, keywords = _score_impact(title, "")
                    articles.append({
                        "source": f"X/@{account}",
                        "feed": f"Nitter ({host.split('//')[1]})",
                        "title": title[:200],
                        "link": link,
                        "published": pub_date,
                        "summary": title[:300],
                        "impact_score": score,
                        "impact_level": level,
                        "impact_keywords": keywords,
                    })

                # If we got results from this host, don't try others
                if articles:
                    break
            except Exception as e:
                logger.debug(f"Nitter parse failed for {host}/{account}: {e}")
                continue

        if articles:
            break

    return articles


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
        min_impact: Minimum impact level to include: 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'.

    Returns:
        Dict with articles sorted by impact score.
    """
    all_categories = list(NEWS_FEEDS.keys())

    # Select feeds
    if category == "all":
        feeds = []
        for cat_feeds in NEWS_FEEDS.values():
            feeds.extend(cat_feeds)
    elif category in NEWS_FEEDS:
        feeds = NEWS_FEEDS[category]
    else:
        return {
            "error": f"Unknown category '{category}'. Available: {', '.join(all_categories)}, or 'all'.",
        }

    # Fetch all RSS feeds concurrently
    tasks = [fetch_rss_feed(url, name, hours) for url, name in feeds]

    # Add direct scraping for Reuters and Twitter
    if category in ("reuters", "all"):
        tasks.append(_scrape_reuters_page())
    if category in ("twitter", "all"):
        tasks.append(_scrape_twitter_trends())

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect all articles
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

    # Summary stats
    critical = sum(1 for a in filtered if a["impact_level"] == "CRITICAL")
    high = sum(1 for a in filtered if a["impact_level"] == "HIGH")
    medium = sum(1 for a in filtered if a["impact_level"] == "MEDIUM")
    low = sum(1 for a in filtered if a["impact_level"] == "LOW")

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
        "articles": filtered,
        "sources_checked": [name for _, name in feeds]
            + (["Reuters Direct Scrape"] if category in ("reuters", "all") else [])
            + (["X/Twitter Nitter Scrape"] if category in ("twitter", "all") else []),
        "errors": errors if errors else None,
    }
