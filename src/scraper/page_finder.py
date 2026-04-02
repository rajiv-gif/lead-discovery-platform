"""Supplemental page discovery from a homepage's internal links.

Strategy
--------
1. Parse all ``<a href="...">`` links from the homepage HTML.
2. Keep only same-origin, non-media internal links.
3. Classify each link using ``classify_url()``.
4. For each target page type (ABOUT → CONTACT → TEAM → SERVICES → OTHER),
   select the **shortest-path** candidate that has not already been chosen.
   At most one URL per PageType is returned.

The caller (runner) decides which types to persist.  The preferred types in
priority order are: ABOUT, CONTACT, TEAM, then SERVICES, OTHER as fallbacks.

Public API
----------
``find_supplemental_urls(homepage_url, html) -> dict[PageType, str]``
    Return a mapping of ``PageType → absolute URL``.  The homepage itself
    and HOMEPAGE-classified links are excluded from results.
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

from src.models.enums import PageType
from src.scraper.classifier import classify_url

# Well-known paths used by Shopify, WooCommerce and other ecommerce platforms.
# Probed as fallbacks when no CONTACT or ABOUT page is found via link-following.
_ECOMMERCE_FALLBACK_PATHS: dict[PageType, list[str]] = {
    PageType.CONTACT: [
        "/pages/contact",
        "/pages/contact-us",
        "/contact",
        "/contact-us",
        "/pages/get-in-touch",
    ],
    PageType.ABOUT: [
        "/pages/about",
        "/pages/about-us",
        "/about",
        "/about-us",
        "/pages/our-story",
    ],
}

log = logging.getLogger(__name__)

# Types to look for, in priority order.
_TARGET_TYPES: list[PageType] = [
    PageType.ABOUT,
    PageType.CONTACT,
    PageType.TEAM,
    PageType.SERVICES,
    PageType.OTHER,
]

# File extensions that indicate non-HTML resources (skip these)
_SKIP_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".mp4", ".mp3", ".avi", ".mov", ".zip", ".tar", ".gz",
    ".css", ".js",
}


def _is_same_origin(base_netloc: str, href: str) -> bool:
    parsed = urlparse(href)
    if not parsed.scheme:
        return True  # relative URL
    if parsed.scheme not in ("http", "https"):
        return False
    return parsed.netloc.lower() == base_netloc.lower()


def _skip_extension(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in _SKIP_EXTENSIONS)


def _extract_links(base_url: str, html: str) -> list[str]:
    """Return a list of absolute internal URLs found in *html*."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        log.warning("BS4 parsing failed in page_finder: %s", exc)
        return []

    base_netloc = urlparse(base_url).netloc.lower()
    links: list[str] = []

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if not _is_same_origin(base_netloc, absolute):
            continue
        if _skip_extension(parsed.path):
            continue
        # Strip fragment and query for dedup
        clean = absolute.split("#")[0].split("?")[0]
        if clean not in links:
            links.append(clean)

    return links


def find_supplemental_urls(
    homepage_url: str,
    html: str,
) -> dict[PageType, str]:
    """Return a mapping of ``PageType → best candidate URL`` from *html*.

    Only types in ``_TARGET_TYPES`` (ABOUT, CONTACT, TEAM, SERVICES, OTHER)
    are returned — HOMEPAGE is never included.  At most one URL per type.

    Candidate selection: for each type, the link with the **shortest path**
    is preferred (shortest path ≈ most direct page on the site).
    """
    links = _extract_links(homepage_url, html)
    log.debug("page_finder found %d internal links on %r", len(links), homepage_url)

    # Group by page type, keeping all candidates
    by_type: dict[PageType, list[str]] = {t: [] for t in _TARGET_TYPES}
    for link in links:
        page_type = classify_url(link)
        if page_type == PageType.HOMEPAGE:
            continue
        if page_type in by_type:
            by_type[page_type].append(link)

    # Select best (shortest path) per type — ensure no URL is reused
    result: dict[PageType, str] = {}
    used_urls: set[str] = set()

    for page_type in _TARGET_TYPES:
        candidates = [u for u in by_type[page_type] if u not in used_urls]
        if not candidates:
            continue
        # Prefer shortest path length as a proxy for "most direct" page
        best = min(candidates, key=lambda u: len(urlparse(u).path))
        result[page_type] = best
        used_urls.add(best)

    # For any target type still missing, probe well-known ecommerce paths.
    # The scraper handles 404s gracefully so probing non-existent paths is safe.
    parsed_base = urlparse(homepage_url)
    origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    for page_type, paths in _ECOMMERCE_FALLBACK_PATHS.items():
        if page_type not in result:
            for path in paths:
                candidate = origin + path
                if candidate not in used_urls:
                    result[page_type] = candidate
                    used_urls.add(candidate)
                    log.debug(
                        "page_finder using ecommerce fallback path %r for %s on %r",
                        path, page_type.value, homepage_url,
                    )
                    break

    log.debug(
        "page_finder selected %d supplemental pages for %r: %s",
        len(result),
        homepage_url,
        {t.value: u for t, u in result.items()},
    )
    return result
