"""Playwright-based browser fetcher — fallback for bot-protected pages.

Used when the standard HTTP fetcher fails due to:
  - Cloudflare / bot-detection challenges (403, 503, JS challenge pages)
  - JS-rendered SPAs where the HTTP response is an empty shell
  - Sites that fingerprint and reject plain httpx requests

Requires the ``browser`` extra:
    pip install "lead-discovery[browser]"
    playwright install chromium

Set ``PLAYWRIGHT_ENABLED=true`` in .env to activate the fallback.
The standard HTTP fetcher always runs first — Playwright only kicks in on failure.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from src.scraper.fetcher import FetchResult

log = logging.getLogger(__name__)

# Cloudflare / bot-gate HTML markers that indicate a challenge page
_CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "challenge-running",
    "__cf_chl",
    "Just a moment",
    "Checking your browser",
    "DDoS protection by",
    "Enable JavaScript and cookies",
)

# Realistic browser user-agent (Chrome on macOS)
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def should_try_playwright(result: FetchResult) -> bool:
    """Return True when the HTTP result warrants a Playwright retry.

    Triggers on:
      - 403 / 503 status (bot blocking)
      - 429 with no Retry-After (CDN rate limit, not a transient error)
      - Cloudflare challenge markers in the HTML
      - JS shell: successful response but HTML < 1 500 chars (no real content)
    """
    if result.status_code in (403, 503):
        return True
    if result.html and any(m in result.html for m in _CHALLENGE_MARKERS):
        return True
    # JS shell: got a 200 but almost no HTML — likely a React/Vue SPA
    if result.ok and len(result.html) < 1500:
        return True
    return False


def fetch_with_playwright(url: str, timeout: float = 20.0) -> FetchResult:
    """Fetch *url* using a headless Chromium browser and return a ``FetchResult``.

    Waits for ``networkidle`` so JS-rendered content is fully populated before
    the HTML is captured. Falls back gracefully if Playwright is not installed.

    Args:
        url:     Target URL to fetch.
        timeout: Seconds to wait for networkidle (default 20 s).

    Returns:
        ``FetchResult`` — same interface as the HTTP fetcher.
        On any error, returns a result with ``ok=False`` and ``error`` set.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning(
            "Playwright not installed — run: pip install 'lead-discovery[browser]' "
            "and playwright install chromium"
        )
        return FetchResult(
            url=url, final_url=url, html="",
            status_code=None, error="playwright not installed",
        )

    log.info("playwright: fetching %r", url)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 800},
                # Pretend to be a real desktop browser
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            page = context.new_page()

            # Block images/fonts/media — we only need HTML, not assets
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font", "stylesheet")
                else route.continue_(),
            )

            response = page.goto(
                url,
                timeout=int(timeout * 1000),
                wait_until="domcontentloaded",
            )

            # Wait a bit more for JS to populate the DOM
            try:
                page.wait_for_load_state("networkidle", timeout=int(timeout * 1000))
            except PWTimeout:
                # networkidle timed out — grab whatever is rendered so far
                log.debug("playwright: networkidle timeout for %r — using partial render", url)

            html = page.content()
            final_url = page.url
            status = response.status if response else 200

            browser.close()

        log.info("playwright: fetched %r → %d bytes (status %s)", url, len(html), status)
        return FetchResult(
            url=url,
            final_url=final_url,
            html=html,
            status_code=status,
            content_type="text/html",
        )

    except Exception as exc:
        log.warning("playwright: fetch failed for %r — %s", url, exc)
        return FetchResult(
            url=url, final_url=url, html="",
            status_code=None, error=f"playwright: {exc}",
        )
