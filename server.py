"""
MCP WebScraper Server
=====================
A full-fledged MCP (Model Context Protocol) server that provides powerful
web scraping tools. Connect from Claude Desktop, Claude Code, or any MCP client.

Tools provided:
  - fetch_page        : Fetch raw HTML from any URL (static or JS-rendered)
  - extract_text      : Get clean readable text or markdown from a URL
  - extract_article   : Extract the main article content (readability)
  - extract_links     : Get all links from a page
  - extract_tables    : Extract HTML tables as structured JSON
  - extract_metadata  : Get page metadata (OG, Twitter cards, JSON-LD, etc.)
  - extract_images    : Get all images from a page
  - take_screenshot   : Capture a full-page screenshot (PNG, base64)
  - crawl_site        : Crawl multiple pages from a site
  - search_google     : Search Google and return results
"""

import asyncio
import base64
import json
import logging
from typing import Any
from urllib.parse import urljoin, urlparse, quote_plus

from mcp.server.fastmcp import FastMCP

from mcp_webscraper.utils.fetcher import fetch_static, fetch_dynamic, take_screenshot as _take_screenshot
from mcp_webscraper.utils.parser import (
    extract_clean_text,
    extract_readable_article,
    extract_links as _extract_links,
    extract_tables as _extract_tables,
    extract_metadata as _extract_metadata,
    extract_images as _extract_images,
)
from mcp_webscraper.tools.news import fetch_news as _fetch_news

# ── Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mcp-webscraper")

mcp = FastMCP(
    "WebScraper",
    instructions=(
        "A full-fledged web scraping MCP server. "
        "Fetch pages, extract text/tables/links/metadata, take screenshots, "
        "crawl sites, and search Google — all via MCP tools."
    ),
)


# ── Helper ────────────────────────────────────────────────────────────
async def _fetch(url: str, javascript: bool = False, wait_for: str | None = None):
    """Internal helper to fetch a page."""
    if javascript:
        return await fetch_dynamic(url, wait_for=wait_for)
    return await fetch_static(url)


def _truncate(text: str, max_length: int = 100_000) -> str:
    """Truncate text to avoid overwhelming the LLM context."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"\n\n... [truncated — showing {max_length:,} of {len(text):,} characters]"


# ══════════════════════════════════════════════════════════════════════
#  TOOL 1: fetch_page
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def fetch_page(
    url: str,
    javascript: bool = False,
    wait_for: str | None = None,
) -> str:
    """
    Fetch the raw HTML of a web page.

    Args:
        url: The URL to fetch.
        javascript: If True, uses a headless browser (Playwright) to render JavaScript.
                    Use this for SPAs, dynamic content, or pages behind JS frameworks.
        wait_for: CSS selector to wait for before capturing (only when javascript=True).

    Returns:
        The raw HTML content of the page.
    """
    result = await _fetch(url, javascript=javascript, wait_for=wait_for)
    if result.error:
        return f"Error fetching {url}: {result.error}"

    return _truncate(result.html)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 2: extract_text
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def extract_text(
    url: str,
    output_format: str = "text",
    javascript: bool = False,
    wait_for: str | None = None,
) -> str:
    """
    Fetch a page and extract its clean, readable text content.

    Args:
        url: The URL to fetch.
        output_format: 'text' for plain text, 'markdown' for Markdown.
        javascript: Use headless browser for JS-rendered pages.
        wait_for: CSS selector to wait for (only when javascript=True).

    Returns:
        Clean text content extracted from the page.
    """
    result = await _fetch(url, javascript=javascript, wait_for=wait_for)
    if result.error:
        return f"Error fetching {url}: {result.error}"

    text = extract_clean_text(result.html, output_format=output_format)
    return _truncate(text)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 3: extract_article
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def extract_article(
    url: str,
    javascript: bool = False,
) -> str:
    """
    Extract the main article/content from a page using readability algorithms.
    Best for news articles, blog posts, and documentation pages.

    Args:
        url: The URL to fetch.
        javascript: Use headless browser for JS-rendered pages.

    Returns:
        JSON with title, content_text, and content_html of the article.
    """
    result = await _fetch(url, javascript=javascript)
    if result.error:
        return f"Error fetching {url}: {result.error}"

    article = extract_readable_article(result.html)
    article["source_url"] = result.final_url or url
    return json.dumps(article, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 4: extract_links
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def extract_links(
    url: str,
    javascript: bool = False,
    filter_external: bool | None = None,
) -> str:
    """
    Extract all links from a web page.

    Args:
        url: The URL to fetch.
        javascript: Use headless browser for JS-rendered pages.
        filter_external: If True, return only external links. If False, only internal.
                         If None, return all links.

    Returns:
        JSON array of links with url, text, and is_external flag.
    """
    result = await _fetch(url, javascript=javascript)
    if result.error:
        return f"Error fetching {url}: {result.error}"

    base_url = result.final_url or url
    links = _extract_links(result.html, base_url=base_url)

    if filter_external is True:
        links = [l for l in links if l.get("is_external")]
    elif filter_external is False:
        links = [l for l in links if not l.get("is_external")]

    return json.dumps({
        "source_url": base_url,
        "total_links": len(links),
        "links": links,
    }, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 5: extract_tables
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def extract_tables(
    url: str,
    javascript: bool = False,
) -> str:
    """
    Extract all HTML tables from a page as structured JSON data.
    Great for scraping data tables, pricing tables, comparison charts, etc.

    Args:
        url: The URL to fetch.
        javascript: Use headless browser for JS-rendered pages.

    Returns:
        JSON with all tables found, including headers and rows.
    """
    result = await _fetch(url, javascript=javascript)
    if result.error:
        return f"Error fetching {url}: {result.error}"

    tables = _extract_tables(result.html)

    return json.dumps({
        "source_url": result.final_url or url,
        "tables_found": len(tables),
        "tables": tables,
    }, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 6: extract_metadata
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def extract_metadata(
    url: str,
    javascript: bool = False,
) -> str:
    """
    Extract page metadata: title, description, Open Graph tags, Twitter cards,
    JSON-LD structured data, canonical URL, language, and more.

    Args:
        url: The URL to fetch.
        javascript: Use headless browser for JS-rendered pages.

    Returns:
        JSON with all metadata found on the page.
    """
    result = await _fetch(url, javascript=javascript)
    if result.error:
        return f"Error fetching {url}: {result.error}"

    metadata = _extract_metadata(result.html, url=result.final_url or url)
    return json.dumps(metadata, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 7: extract_images
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def extract_images(
    url: str,
    javascript: bool = False,
) -> str:
    """
    Extract all images from a web page with their src, alt text, and dimensions.

    Args:
        url: The URL to fetch.
        javascript: Use headless browser for JS-rendered pages.

    Returns:
        JSON array of images found on the page.
    """
    result = await _fetch(url, javascript=javascript)
    if result.error:
        return f"Error fetching {url}: {result.error}"

    base_url = result.final_url or url
    images = _extract_images(result.html, base_url=base_url)

    return json.dumps({
        "source_url": base_url,
        "total_images": len(images),
        "images": images,
    }, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 8: take_screenshot
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def screenshot(
    url: str,
    full_page: bool = True,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """
    Take a screenshot of a web page using a headless browser.
    Returns the screenshot as a base64-encoded PNG string.

    Args:
        url: The URL to screenshot.
        full_page: If True, captures the entire scrollable page. If False, viewport only.
        width: Viewport width in pixels.
        height: Viewport height in pixels.

    Returns:
        Base64-encoded PNG screenshot, or an error message.
    """
    png_bytes, error = await _take_screenshot(url, full_page=full_page, width=width, height=height)

    if error:
        return f"Error taking screenshot of {url}: {error}"

    b64 = base64.b64encode(png_bytes).decode("utf-8")
    return json.dumps({
        "source_url": url,
        "format": "png",
        "encoding": "base64",
        "full_page": full_page,
        "viewport": f"{width}x{height}",
        "size_bytes": len(png_bytes),
        "data": b64,
    }, indent=2)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 9: crawl_site
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def crawl_site(
    url: str,
    max_pages: int = 10,
    same_domain_only: bool = True,
    javascript: bool = False,
    extract: str = "text",
) -> str:
    """
    Crawl a website starting from a URL. Follows links up to max_pages.

    Args:
        url: The starting URL.
        max_pages: Maximum number of pages to crawl (1-50).
        same_domain_only: If True, only follow links on the same domain.
        javascript: Use headless browser for each page.
        extract: What to extract per page: 'text', 'markdown', 'links', 'metadata'.

    Returns:
        JSON with crawled pages and their extracted content.
    """
    max_pages = min(max(1, max_pages), 50)
    base_domain = urlparse(url).netloc

    visited: set[str] = set()
    queue: list[str] = [url]
    results: list[dict] = []

    while queue and len(visited) < max_pages:
        current_url = queue.pop(0)

        # Normalize URL
        parsed = urlparse(current_url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if normalized in visited:
            continue

        visited.add(normalized)
        logger.info(f"Crawling [{len(visited)}/{max_pages}]: {current_url}")

        fetch_result = await _fetch(current_url, javascript=javascript)
        if fetch_result.error:
            results.append({
                "url": current_url,
                "error": fetch_result.error,
            })
            continue

        page_data: dict[str, Any] = {
            "url": fetch_result.final_url or current_url,
            "status_code": fetch_result.status_code,
        }

        # Extract requested content
        if extract == "text":
            page_data["content"] = extract_clean_text(fetch_result.html, "text")[:5000]
        elif extract == "markdown":
            page_data["content"] = extract_clean_text(fetch_result.html, "markdown")[:5000]
        elif extract == "links":
            page_data["links"] = _extract_links(fetch_result.html, base_url=current_url)
        elif extract == "metadata":
            page_data["metadata"] = _extract_metadata(fetch_result.html, url=current_url)

        results.append(page_data)

        # Discover new links
        links = _extract_links(fetch_result.html, base_url=current_url)
        for link in links:
            link_url = link["url"]
            link_domain = urlparse(link_url).netloc

            if same_domain_only and link_domain != base_domain:
                continue

            link_normalized = f"{urlparse(link_url).scheme}://{link_domain}{urlparse(link_url).path}"
            if link_normalized not in visited:
                queue.append(link_url)

    return json.dumps({
        "start_url": url,
        "pages_crawled": len(results),
        "max_pages": max_pages,
        "pages": results,
    }, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 10: search_google
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def search_google(
    query: str,
    num_results: int = 10,
) -> str:
    """
    Search Google and return the top results with titles, URLs, and snippets.

    Args:
        query: The search query string.
        num_results: Number of results to return (1-20).

    Returns:
        JSON array of search results with title, url, and snippet.
    """
    num_results = min(max(1, num_results), 20)
    encoded_query = quote_plus(query)
    search_url = f"https://www.google.com/search?q={encoded_query}&num={num_results}&hl=en"

    result = await fetch_static(search_url)
    if result.error:
        return f"Error searching Google: {result.error}"

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(result.html, "lxml")

    search_results = []
    for g in soup.select("div.g"):
        title_tag = g.select_one("h3")
        link_tag = g.select_one("a[href]")
        snippet_tag = g.select_one("div.VwiC3b, span.aCOpRe, div.s")

        if not title_tag or not link_tag:
            continue

        href = link_tag["href"]
        if href.startswith("/url?q="):
            href = href.split("/url?q=")[1].split("&")[0]

        search_results.append({
            "title": title_tag.get_text(strip=True),
            "url": href,
            "snippet": snippet_tag.get_text(strip=True) if snippet_tag else "",
        })

    return json.dumps({
        "query": query,
        "total_results": len(search_results),
        "results": search_results[:num_results],
    }, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 11: get_news
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def get_news(
    category: str = "india_markets",
    hours: int = 48,
    min_impact: str = "LOW",
) -> str:
    """
    Fetch latest news from multiple RSS sources with impact scoring.
    Returns articles sorted by impact (CRITICAL > HIGH > MEDIUM > LOW).

    Args:
        category: News category to fetch. Options:
                  - 'india_markets' : ET Markets, ET Stocks, Moneycontrol, LiveMint (default)
                  - 'global_markets': Yahoo Finance, BBC Business, NYT Business, CNBC
                  - 'reuters'       : Reuters via Google News + direct website scrape
                  - 'twitter'       : X/Twitter via Nitter mirrors + Google News
                  - 'crypto'        : CoinTelegraph, Google News Crypto
                  - 'technology'    : TechCrunch, The Verge, Google News Tech
                  - 'all'           : All sources combined
        hours: Time window in hours (default 48). Set to 24 for last day only.
        min_impact: Minimum impact level to return. Options: 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'.

    Returns:
        JSON with articles, impact scores, and summary statistics.
    """
    result = await _fetch_news(category=category, hours=hours, min_impact=min_impact)
    return json.dumps(result, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  TOOL 12: get_high_impact_news
# ══════════════════════════════════════════════════════════════════════
@mcp.tool()
async def get_high_impact_news(
    category: str = "india_markets",
    hours: int = 48,
) -> str:
    """
    Fetch ONLY high-impact and critical news from the last 48 hours.
    Shortcut for get_news with min_impact='HIGH'. Use this when you only
    want market-moving, critical headlines.

    Args:
        category: 'india_markets', 'global_markets', 'reuters', 'twitter', 'crypto', 'technology', or 'all'.
        hours: Time window in hours (default 48).

    Returns:
        JSON with only HIGH and CRITICAL impact articles.
    """
    result = await _fetch_news(category=category, hours=hours, min_impact="HIGH")
    return json.dumps(result, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
#  Resources
# ══════════════════════════════════════════════════════════════════════
@mcp.resource("webscraper://info")
def get_server_info() -> str:
    """Get information about the MCP WebScraper server and its capabilities."""
    return json.dumps({
        "name": "MCP WebScraper",
        "version": "1.0.0",
        "description": "Full-fledged web scraping MCP server",
        "tools": [
            "fetch_page - Get raw HTML from any URL",
            "extract_text - Get clean text or markdown from a URL",
            "extract_article - Extract main article content (readability)",
            "extract_links - Get all links from a page",
            "extract_tables - Extract HTML tables as structured JSON",
            "extract_metadata - Get Open Graph, Twitter Card, JSON-LD metadata",
            "extract_images - Get all images from a page",
            "screenshot - Capture a full-page PNG screenshot",
            "crawl_site - Crawl multiple pages from a site",
            "search_google - Search Google and return results",
            "get_news - Fetch 48hr news with impact scoring (multiple categories)",
            "get_high_impact_news - Get only CRITICAL & HIGH impact news",
        ],
        "features": [
            "JavaScript rendering via Playwright",
            "Static fetching via httpx",
            "Automatic content extraction",
            "Readability-based article extraction",
            "Markdown output support",
            "Site crawling with link following",
        ],
    }, indent=2)


# ══════════════════════════════════════════════════════════════════════
#  Entrypoint
# ══════════════════════════════════════════════════════════════════════
def main():
    """
    Run the MCP WebScraper server.

    Transport modes:
      - stdio   : For local use (Claude Desktop, Claude Code)
      - sse     : For network/cloud deployment (anyone can connect via HTTP)

    Set via environment variable MCP_TRANSPORT=sse or pass --sse flag.
    Set MCP_HOST and MCP_PORT to control the SSE server binding.
    """
    import os
    import sys

    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))

    # CLI flag override
    if "--sse" in sys.argv:
        transport = "sse"
    if "--stdio" in sys.argv:
        transport = "stdio"

    if transport == "sse":
        logger.info(f"Starting MCP WebScraper server (SSE) on http://{host}:{port}")
        mcp.run(transport="sse", host=host, port=port)
    else:
        logger.info("Starting MCP WebScraper server (stdio)")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
