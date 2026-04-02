"""Web search client for ecommerce lead discovery.

Uses DuckDuckGo's unofficial HTML endpoint — free, no API key required.
Returns a list of ``WebSearchResult`` objects (url, title, snippet).

The client is intentionally thin so it can be swapped for Serper.dev or
another paid provider later by replacing this module only.

Limitations:
  - DDG HTML structure can change without notice; parser may need updates.
  - Rate-limited by DDG; use ``rate_limit_delay`` (default 2s) between calls.
  - Returns ~10 organic results per query (DDG first page).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Domains to skip — ad networks, social media, aggregators that aren't leads
_SKIP_DOMAINS = frozenset(
    {
        "duckduckgo.com",
        "google.com",
        "bing.com",
        "yahoo.com",
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "youtube.com",
        "tiktok.com",
        "pinterest.com",
        "reddit.com",
        "wikipedia.org",
        "amazon.com",
        "ebay.com",
        "etsy.com",
        "walmart.com",
        "target.com",
    }
)


@dataclass
class WebSearchResult:
    """A single organic result from a web search query."""

    url: str
    title: str
    snippet: str
    domain: str
    query: str  # The query that produced this result


class WebSearchError(Exception):
    """Raised when the web search request fails."""


class DuckDuckGoClient:
    """Minimal DuckDuckGo HTML scraper for organic search results.

    Args:
        rate_limit_delay: Seconds to wait between consecutive requests.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        rate_limit_delay: float = 2.0,
        timeout: float = 15.0,
    ) -> None:
        self._delay = rate_limit_delay
        self._timeout = timeout
        self._last_request_at: float = 0.0

    def search(self, query: str, max_results: int = 10) -> list[WebSearchResult]:
        """Search DuckDuckGo and return up to *max_results* organic results.

        Fetches multiple pages if needed to reach *max_results*.  Each DDG
        page yields ~10 organic results; pages are fetched sequentially with
        the configured rate-limit delay between them.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return (default 10).

        Returns:
            List of ``WebSearchResult`` objects.  May be empty if DDG returns
            no usable results or the HTML structure has changed.

        Raises:
            WebSearchError: On HTTP error or timeout (first page only).
        """
        params: dict = {"q": query, "kl": "us-en"}
        all_results: list[WebSearchResult] = []
        page = 1

        while len(all_results) < max_results:
            self._rate_limit()
            try:
                response = httpx.post(
                    _DDG_URL,
                    data=params,
                    headers=_HEADERS,
                    timeout=self._timeout,
                    follow_redirects=True,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if page == 1:
                    raise WebSearchError(
                        f"DuckDuckGo returned HTTP {exc.response.status_code} for query {query!r}"
                    ) from exc
                log.debug("DDG page %d HTTP error — stopping pagination: %s", page, exc)
                break
            except httpx.RequestError as exc:
                if page == 1:
                    raise WebSearchError(
                        f"DuckDuckGo request failed for query {query!r}: {exc}"
                    ) from exc
                log.debug("DDG page %d request error — stopping pagination: %s", page, exc)
                break

            page_results = self._parse_results(response.text, query)
            log.debug(
                "DDG query %r page %d → %d results", query, page, len(page_results)
            )

            if not page_results:
                break  # No more results

            # Only add results we haven't seen yet (by domain)
            seen = {r.domain for r in all_results}
            new_results = [r for r in page_results if r.domain not in seen]
            all_results.extend(new_results)

            if len(new_results) == 0:
                break  # All results on this page were duplicates — stop

            # Parse next-page params; stop if DDG offers no next page
            next_params = _parse_next_page_params(response.text)
            if not next_params:
                break

            params = {"q": query, "kl": "us-en", **next_params}
            page += 1

        log.debug("DDG query %r → %d total results across %d page(s)", query, len(all_results), page)
        return all_results[:max_results]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Enforce minimum delay between requests."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request_at = time.monotonic()

    def _parse_results(self, html: str, query: str) -> list[WebSearchResult]:
        """Parse DDG HTML response and extract organic result links."""
        soup = BeautifulSoup(html, "html.parser")
        results: list[WebSearchResult] = []

        # DDG HTML results are in <div class="result"> blocks
        for result_div in soup.select("div.result"):
            title_el = result_div.select_one("a.result__a")
            snippet_el = result_div.select_one("a.result__snippet")

            if not title_el:
                continue

            raw_url = title_el.get("href", "")
            title = title_el.get_text(strip=True)
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # DDG may wrap links via a redirect — extract the real URL
            url = _extract_real_url(raw_url)
            if not url:
                continue

            domain = _extract_domain(url)
            if not domain or domain in _SKIP_DOMAINS:
                continue

            results.append(
                WebSearchResult(
                    url=url,
                    title=title,
                    snippet=snippet,
                    domain=domain,
                    query=query,
                )
            )

        return results


def _parse_next_page_params(html: str) -> dict | None:
    """Parse the 'More Results' form params from a DDG HTML response.

    DDG embeds the next-page offset in a hidden ``<input name="s">`` field.
    Returns a dict of all hidden inputs from that form, or None if not found.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        for form in soup.find_all("form"):
            s_input = form.find("input", {"name": "s"})
            if s_input and s_input.get("value"):
                params = {}
                for inp in form.find_all("input", {"type": "hidden"}):
                    name = inp.get("name")
                    value = inp.get("value", "")
                    if name:
                        params[name] = value
                if params:
                    return params
    except Exception as exc:
        log.debug("Failed to parse DDG next-page params: %s", exc)
    return None


def _extract_real_url(href: str) -> str:
    """Extract the real destination URL from a possibly-wrapped DDG href."""
    if not href:
        return ""
    # DDG sometimes uses //duckduckgo.com/l/?uddg=<encoded_url>
    if "uddg=" in href:
        from urllib.parse import parse_qs, urlparse as _up
        try:
            qs = parse_qs(_up(href).query)
            urls = qs.get("uddg", [])
            if urls:
                from urllib.parse import unquote
                return unquote(urls[0])
        except Exception:
            pass
    # Direct link or relative path
    if href.startswith("http"):
        return href
    return ""


def _extract_domain(url: str) -> str:
    """Return the bare domain (no www.) from a URL."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return host.removeprefix("www.")
    except Exception:
        return ""
