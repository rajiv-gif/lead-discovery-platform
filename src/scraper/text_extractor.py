"""HTML-to-plain-text extraction for the scraping stage.

Primary:  ``trafilatura`` — boilerplate-aware extraction tuned for editorial
          and business-page content.
Fallback: ``BeautifulSoup`` — used when trafilatura returns empty or None.
          Strips all tags and collapses whitespace.

Public API
----------
``extract_text(html) -> str``
    Return cleaned plain text; empty string on failure.

``count_words(text) -> int``
    Return the word count of plain text.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def _bs4_fallback(html: str) -> str:
    """Strip all tags and collapse whitespace using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        # Remove script and style elements before getting text
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
    except Exception as exc:
        log.warning("BS4 fallback failed: %s", exc)
        return ""
    # Collapse whitespace
    return re.sub(r"\s+", " ", text).strip()


def extract_text(html: str) -> str:
    """Return boilerplate-stripped plain text for *html*.

    Tries trafilatura first; falls back to BeautifulSoup if the result is
    empty or trafilatura raises.  Returns an empty string if both fail.
    """
    if not html:
        return ""

    # --- Primary: trafilatura ---
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        if text and text.strip():
            return text.strip()
    except Exception as exc:
        log.warning("trafilatura extraction failed: %s", exc)

    # --- Fallback: BeautifulSoup ---
    log.debug("trafilatura returned empty — using BS4 fallback")
    return _bs4_fallback(html)


def count_words(text: str) -> int:
    """Return the number of whitespace-separated tokens in *text*."""
    if not text:
        return 0
    return len(text.split())
