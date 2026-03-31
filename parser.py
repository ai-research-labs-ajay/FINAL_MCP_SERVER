"""
HTML parsing utilities - extract text, links, tables, metadata, and structured data.
"""

import json
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment
from markdownify import markdownify as md

logger = logging.getLogger(__name__)


def extract_clean_text(html: str, output_format: str = "text") -> str:
    """
    Extract clean readable text from HTML.
    output_format: 'text' for plain text, 'markdown' for markdown.
    """
    if output_format == "markdown":
        return md(html, heading_style="ATX", strip=["img", "script", "style"])

    soup = BeautifulSoup(html, "lxml")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
        tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    text = soup.get_text(separator="\n", strip=True)

    # Clean up excessive whitespace
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def extract_readable_article(html: str) -> dict:
    """Extract the main article content using readability."""
    try:
        from readability import Document
        doc = Document(html)
        return {
            "title": doc.title(),
            "content_html": doc.summary(),
            "content_text": extract_clean_text(doc.summary()),
            "short_title": doc.short_title(),
        }
    except Exception as e:
        logger.warning(f"Readability extraction failed: {e}")
        return {
            "title": "",
            "content_html": "",
            "content_text": extract_clean_text(html),
            "short_title": "",
        }


def extract_links(html: str, base_url: str = "") -> list[dict]:
    """Extract all links from HTML with their text and resolved URLs."""
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        # Resolve relative URLs
        if base_url:
            href = urljoin(base_url, href)

        if href in seen:
            continue
        seen.add(href)

        text = a_tag.get_text(strip=True)
        links.append({
            "url": href,
            "text": text or "[no text]",
            "is_external": _is_external(href, base_url) if base_url else None,
        })

    return links


def extract_tables(html: str) -> list[dict]:
    """Extract all HTML tables as structured JSON data."""
    soup = BeautifulSoup(html, "lxml")
    tables = []

    for idx, table in enumerate(soup.find_all("table")):
        rows = []
        headers = []

        # Try to get headers from <thead> or first <tr>
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

        # Collect body rows, skipping the thead rows we already processed
        thead_trs = set()
        if thead:
            for tr in thead.find_all("tr"):
                thead_trs.add(id(tr))

        for tr in table.find_all("tr"):
            if id(tr) in thead_trs:
                continue
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                # If no headers yet, treat first row of <th> as headers
                if not headers and tr.find_all("th"):
                    headers = cells
                    continue
                rows.append(cells)

        # If we got headers, convert rows to dicts
        if headers:
            dict_rows = []
            for row in rows:
                row_dict = {}
                for i, header in enumerate(headers):
                    row_dict[header] = row[i] if i < len(row) else ""
                dict_rows.append(row_dict)
            tables.append({
                "table_index": idx,
                "headers": headers,
                "rows": dict_rows,
                "row_count": len(dict_rows),
            })
        else:
            tables.append({
                "table_index": idx,
                "headers": [],
                "rows": rows,
                "row_count": len(rows),
            })

    return tables


def extract_metadata(html: str, url: str = "") -> dict:
    """Extract page metadata: title, description, Open Graph, Twitter cards, JSON-LD, etc."""
    soup = BeautifulSoup(html, "lxml")
    meta = {
        "url": url,
        "title": "",
        "description": "",
        "canonical": "",
        "language": "",
        "open_graph": {},
        "twitter_card": {},
        "json_ld": [],
        "other_meta": {},
    }

    # Title
    title_tag = soup.find("title")
    if title_tag:
        meta["title"] = title_tag.get_text(strip=True)

    # HTML lang
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        meta["language"] = html_tag["lang"]

    # Canonical
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        meta["canonical"] = canonical["href"]

    # Meta tags
    for tag in soup.find_all("meta"):
        name = tag.get("name", "").lower()
        prop = tag.get("property", "").lower()
        content = tag.get("content", "")

        if name == "description" or prop == "description":
            meta["description"] = content
        elif prop.startswith("og:"):
            meta["open_graph"][prop.replace("og:", "")] = content
        elif name.startswith("twitter:") or prop.startswith("twitter:"):
            key = (name or prop).replace("twitter:", "")
            meta["twitter_card"][key] = content
        elif name and content:
            meta["other_meta"][name] = content

    # JSON-LD structured data
    for script_tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script_tag.string)
            meta["json_ld"].append(data)
        except (json.JSONDecodeError, TypeError):
            pass

    return meta


def extract_images(html: str, base_url: str = "") -> list[dict]:
    """Extract all images with their src, alt text, and dimensions."""
    soup = BeautifulSoup(html, "lxml")
    images = []
    seen = set()

    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or img.get("data-lazy-src", "")
        if not src:
            continue

        if base_url:
            src = urljoin(base_url, src)

        if src in seen:
            continue
        seen.add(src)

        images.append({
            "src": src,
            "alt": img.get("alt", ""),
            "width": img.get("width", ""),
            "height": img.get("height", ""),
            "loading": img.get("loading", ""),
        })

    return images


def _is_external(href: str, base_url: str) -> bool:
    """Check if a URL is external relative to the base URL."""
    try:
        base_domain = urlparse(base_url).netloc
        link_domain = urlparse(href).netloc
        return base_domain != link_domain
    except Exception:
        return False
