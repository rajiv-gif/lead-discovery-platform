"""LinkedIn owner lookup via DuckDuckGo search.

Searches DuckDuckGo for LinkedIn profiles matching a business owner/founder
for a given company name and city. No LinkedIn credentials or API key required —
this uses Google's public index of LinkedIn public profiles via DuckDuckGo.

Returns structured contact data (name, title, linkedin_url) when found.

Rate limit: use a delay of at least 2s between calls to avoid DuckDuckGo blocks.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Titles that unambiguously indicate a business owner/decision-maker.
#
# Deliberately excludes standalone "director", "principal", and "operator":
#   - "director"  → false-matches "Art Director", "Director of Photography"
#   - "principal" → false-matches "Principal Engineer", "Principal Consultant"
#   - "operator"  → false-matches "Machine Operator", "Forklift Operator"
# These tokens are retained only in their compound forms ("managing director")
# where they are unambiguous.
#
# Matching uses word-boundary regex (\b) to prevent sub-string contamination
# and so multi-word phrases like "managing director" are matched as a unit.
_OWNER_TITLES: frozenset[str] = frozenset({
    # Unambiguous standalone roles
    "owner", "founder", "co-founder", "ceo", "proprietor",
    # Positional title (acceptable false-positive rate for VP level)
    "president",
    # Unambiguous compound titles
    "chief executive", "managing director", "managing partner",
})

# Pre-compiled word-boundary patterns, longest first so compound tokens
# ("managing director") are matched before their component words ("director").
_OWNER_TITLE_PATTERNS: list[re.Pattern] = [
    re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)
    for t in sorted(_OWNER_TITLES, key=len, reverse=True)
]

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class LinkedInOwner:
    """A potential business owner found via LinkedIn."""
    full_name: str
    first_name: str
    last_name: str
    title: str
    linkedin_url: str
    confidence: str   # "high" | "medium"


def find_owner(
    company_name: str,
    city: str,
    delay: float = 2.0,
    city_fallback: bool = False,
) -> Optional[LinkedInOwner]:
    """Search DuckDuckGo for the owner/founder of *company_name* in *city*.

    Args:
        company_name: Business name to search for.
        city: City used to narrow the LinkedIn search.
        delay: Seconds to sleep between DuckDuckGo requests.
        city_fallback: When True, re-run the query without the city constraint
            if the city-scoped query returns no usable results.  Defaults to
            False because loose queries produce high false-positive rates for
            common business names (e.g. "Quality Roofing", "Pro Services").
            Enable only via LINKEDIN_CITY_FALLBACK_ENABLED=true.

    Returns:
        The best matching ``LinkedInOwner`` or None if not found.
    """
    query = (
        f'site:linkedin.com/in "{company_name}" '
        f'"{city}" owner OR founder OR president OR CEO'
    )

    results = _ddg_search(query, delay=delay)

    if not results and city_fallback:
        # Looser query — higher recall, higher false-positive rate.
        log.debug(
            "LinkedIn: city-scoped query returned nothing for %r — "
            "trying fallback (no city constraint)", company_name
        )
        query2 = (
            f'site:linkedin.com/in "{company_name}" '
            f'owner OR founder OR president OR CEO'
        )
        results = _ddg_search(query2, delay=delay)

    for result in results[:5]:
        owner = _parse_linkedin_result(result)
        if owner is not None:
            return owner

    return None


def _ddg_search(query: str, delay: float = 2.0) -> list[dict]:
    """POST to DuckDuckGo HTML search and return parsed results."""
    try:
        resp = httpx.post(
            _DDG_HTML_URL,
            data={"q": query, "kl": "us-en", "ia": "web"},
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://duckduckgo.com/",
            },
            timeout=20.0,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        log.warning("DuckDuckGo search error: %s", exc)
        return []
    finally:
        time.sleep(delay)

    if resp.status_code != 200:
        log.warning("DuckDuckGo returned HTTP %d", resp.status_code)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    for result_div in soup.select(".result")[:10]:
        title_el = result_div.select_one(".result__a")
        snippet_el = result_div.select_one(".result__snippet")
        url_el = result_div.select_one(".result__url")

        if not title_el:
            continue

        href = title_el.get("href", "")
        # DuckDuckGo wraps links — extract the actual URL
        actual_url = _extract_actual_url(href)

        results.append({
            "title": title_el.get_text(strip=True),
            "url": actual_url,
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            "display_url": url_el.get_text(strip=True) if url_el else "",
        })

    return results


def _extract_actual_url(href: str) -> str:
    """DuckDuckGo wraps result URLs — try to extract the real target."""
    # Pattern: //duckduckgo.com/l/?uddg=https%3A%2F%2F...
    match = re.search(r'uddg=([^&]+)', href)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1))
    return href


def _parse_linkedin_result(result: dict) -> Optional[LinkedInOwner]:
    """Try to extract owner info from a single DuckDuckGo result."""
    url = result.get("url", "")
    title = result.get("title", "")
    snippet = result.get("snippet", "")

    # Must be a LinkedIn profile URL
    if "linkedin.com/in/" not in url.lower():
        return None

    # Normalise the LinkedIn URL
    linkedin_url = _normalise_linkedin_url(url)
    if not linkedin_url:
        return None

    # Try to extract name + title from the result title
    # LinkedIn titles look like: "John Smith - Owner - ABC Company | LinkedIn"
    # or: "John Smith | LinkedIn"
    owner = _parse_from_title(title, linkedin_url)
    if owner is not None:
        return owner

    # Fallback: try the snippet
    # Snippets sometimes contain "Owner at ABC Company"
    return _parse_from_snippet(snippet, linkedin_url)


def _parse_from_title(title: str, linkedin_url: str) -> Optional[LinkedInOwner]:
    """Parse LinkedIn profile title string."""
    # Remove " | LinkedIn" suffix
    title = re.sub(r'\s*\|\s*LinkedIn\s*$', '', title, flags=re.IGNORECASE).strip()

    parts = [p.strip() for p in title.split(" - ")]
    if len(parts) < 2:
        return None

    name_part = parts[0]
    role_part = parts[1] if len(parts) > 1 else ""

    if not _is_owner_title(role_part):
        return None

    first, last = _split_name(name_part)
    if not first and not last:
        return None

    return LinkedInOwner(
        full_name=name_part,
        first_name=first,
        last_name=last,
        title=role_part,
        linkedin_url=linkedin_url,
        confidence="high",
    )


def _parse_from_snippet(snippet: str, linkedin_url: str) -> Optional[LinkedInOwner]:
    """Try to extract owner info from snippet text."""
    # Pattern: "FirstName LastName · Title at Company"
    match = re.search(
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*[·•]\s*([^·•\n]+?)\s+at\s+',
        snippet,
    )
    if not match:
        return None

    name_part = match.group(1).strip()
    title_part = match.group(2).strip()

    if not _is_owner_title(title_part):
        return None

    first, last = _split_name(name_part)
    return LinkedInOwner(
        full_name=name_part,
        first_name=first,
        last_name=last,
        title=title_part,
        linkedin_url=linkedin_url,
        confidence="medium",
    )


def _is_owner_title(title: str) -> bool:
    """Return True if *title* indicates a business owner/decision-maker.

    Uses pre-compiled word-boundary patterns so tokens like "director" do not
    false-match "Art Director" or "Director of Photography", and "principal"
    does not match "Principal Software Engineer".
    """
    return any(pat.search(title) for pat in _OWNER_TITLE_PATTERNS)


def _split_name(full_name: str) -> tuple[str, str]:
    """Split 'First Last' or 'First Middle Last' into (first, last)."""
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def _normalise_linkedin_url(url: str) -> Optional[str]:
    """Return a clean https://linkedin.com/in/slug URL, or None."""
    match = re.search(r'linkedin\.com/in/([a-zA-Z0-9\-_%]+)', url)
    if not match:
        return None
    slug = match.group(1).rstrip("/")
    return f"https://www.linkedin.com/in/{slug}"
