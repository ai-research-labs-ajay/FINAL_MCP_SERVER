"""
HTTP fetcher with support for both static (httpx) and dynamic (Playwright) page loading.
"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Default headers to mimic a real browser
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class FetchResult:
    """Result of a page fetch operation."""
    url: str
    status_code: int
    html: str
    headers: dict = field(default_factory=dict)
    final_url: str = ""
    error: Optional[str] = None


async def fetch_static(
    url: str,
    timeout: int = 30,
    headers: Optional[dict] = None,
    follow_redirects: bool = True,
) -> FetchResult:
    """Fetch a page using httpx (no JavaScript execution)."""
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}

    try:
        async with httpx.AsyncClient(
            follow_redirects=follow_redirects,
            timeout=httpx.Timeout(timeout),
            headers=merged_headers,
        ) as client:
            response = await client.get(url)
            return FetchResult(
                url=url,
                status_code=response.status_code,
                html=response.text,
                headers=dict(response.headers),
                final_url=str(response.url),
            )
    except httpx.TimeoutException:
        return FetchResult(url=url, status_code=0, html="", error=f"Timeout after {timeout}s")
    except Exception as e:
        return FetchResult(url=url, status_code=0, html="", error=str(e))


async def fetch_dynamic(
    url: str,
    timeout: int = 30000,
    wait_for: Optional[str] = None,
    wait_until: str = "networkidle",
) -> FetchResult:
    """Fetch a page using Playwright (full JavaScript execution)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return FetchResult(
            url=url, status_code=0, html="",
            error="Playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            response = await page.goto(url, wait_until=wait_until, timeout=timeout)

            if wait_for:
                await page.wait_for_selector(wait_for, timeout=timeout)

            # Let any lazy-loaded content settle
            await page.wait_for_timeout(1000)

            html = await page.content()
            final_url = page.url
            status = response.status if response else 0

            await browser.close()

            return FetchResult(
                url=url,
                status_code=status,
                html=html,
                final_url=final_url,
            )
    except Exception as e:
        return FetchResult(url=url, status_code=0, html="", error=str(e))


async def take_screenshot(
    url: str,
    full_page: bool = True,
    timeout: int = 30000,
    width: int = 1920,
    height: int = 1080,
) -> tuple[Optional[bytes], Optional[str]]:
    """Take a screenshot of a page using Playwright. Returns (png_bytes, error)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None, "Playwright not installed. Run: pip install playwright && playwright install chromium"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                user_agent=DEFAULT_HEADERS["User-Agent"],
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=timeout)
            await page.wait_for_timeout(1500)

            screenshot_bytes = await page.screenshot(full_page=full_page, type="png")
            await browser.close()
            return screenshot_bytes, None
    except Exception as e:
        return None, str(e)
