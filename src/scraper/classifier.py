"""Page type classifier for the scraping stage.

Two complementary classifiers:

``classify_url(url)``
    Fast, URL-path-only heuristic.  Works before any page is fetched.

``classify_page(url, title, h1)``
    Richer heuristic that combines URL path with the page's ``<title>`` and
    first ``<h1>`` text.  Prefer this when the HTML is already available.

Both return a ``PageType`` value.  All keywords are matched case-insensitively
against the full URL path or the text fields.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from src.models.enums import PageType

# ---------------------------------------------------------------------------
# Keyword tables — ordered by specificity within each type
# ---------------------------------------------------------------------------

_ABOUT_PATTERNS = re.compile(
    r"\b(about[-_]?us|about|who[-_]we[-_]are|our[-_]story|our[-_]practice|"
    r"the[-_]practice)\b",
    re.IGNORECASE,
)

_CONTACT_PATTERNS = re.compile(
    r"\b(contact[-_]?us|contact|get[-_]in[-_]touch|find[-_]us|"
    r"appointments?|book[-_]an[-_]appointment|locations?|directions?)\b",
    re.IGNORECASE,
)

_TEAM_PATTERNS = re.compile(
    r"\b(meet[-_]the[-_]team|our[-_]team|team|staff|dentists?|practitioners?|"
    r"specialists?|our[-_]dentists?|dr\.?|doctors?|meet[-_]us)\b",
    re.IGNORECASE,
)

_SERVICES_PATTERNS = re.compile(
    r"\b(services?|treatments?|procedures?|what[-_]we[-_]do|"
    r"dental[-_]care|implants?|orthodontics?|whitening|cosmetic)\b",
    re.IGNORECASE,
)


def _url_path(url: str) -> str:
    """Return the lowercased path component of *url*."""
    return urlparse(url).path.lower()


def classify_url(url: str) -> PageType:
    """Classify a page based solely on its URL path.

    Returns ``PageType.HOMEPAGE`` when the path is "/" or empty.
    """
    path = _url_path(url)
    if not path or path == "/":
        return PageType.HOMEPAGE

    if _ABOUT_PATTERNS.search(path):
        return PageType.ABOUT
    if _CONTACT_PATTERNS.search(path):
        return PageType.CONTACT
    if _TEAM_PATTERNS.search(path):
        return PageType.TEAM
    if _SERVICES_PATTERNS.search(path):
        return PageType.SERVICES

    return PageType.OTHER


def classify_page(
    url: str,
    title: str | None = None,
    h1: str | None = None,
) -> PageType:
    """Classify a page using URL path, page title, and first H1 heading.

    The URL is checked first (fast path).  If the URL alone gives a definitive
    non-OTHER result, that result is returned immediately.  For OTHER URLs the
    title and h1 are checked to see if a better classification is possible.
    """
    url_type = classify_url(url)
    if url_type != PageType.OTHER:
        return url_type

    # Combine title + h1 for text-based classification
    text = " ".join(filter(None, [title, h1])).strip()
    if not text:
        return PageType.OTHER

    if _ABOUT_PATTERNS.search(text):
        return PageType.ABOUT
    if _CONTACT_PATTERNS.search(text):
        return PageType.CONTACT
    if _TEAM_PATTERNS.search(text):
        return PageType.TEAM
    if _SERVICES_PATTERNS.search(text):
        return PageType.SERVICES

    return PageType.OTHER
