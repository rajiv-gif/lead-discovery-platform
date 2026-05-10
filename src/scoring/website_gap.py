"""Website gap signal detection for WEB_AGENCY campaigns.

Reads already-saved HTML pages (zero extra network calls) and the Company
``has_website`` flag set during Places discovery to produce a
:class:`WebsiteGapSignals` snapshot.

These signals feed Dimension H of the scoring model, which only activates
when ``campaign.campaign_goal == CampaignGoal.WEB_AGENCY``.
"""
from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns — applied to raw HTML bytes decoded as UTF-8 (errors=ignore)
# ---------------------------------------------------------------------------

# Copyright year: © 2019, Copyright 2018, &copy; 2017, (c) 2016 …
_COPYRIGHT_RE = re.compile(
    r"(?:©|&copy;|\(c\)|copyright)\s*(\d{4})",
    re.IGNORECASE,
)

# Social media links in href attributes
_SOCIAL_RE = re.compile(
    r'href=["\']https?://(?:www\.)?(?:facebook\.com|instagram\.com|linkedin\.com|twitter\.com|x\.com)',
    re.IGNORECASE,
)

# Mobile viewport meta tag
_VIEWPORT_RE = re.compile(
    r'<meta[^>]+name=["\']viewport["\']',
    re.IGNORECASE,
)

# HTTPS check — base_url passed from outside


# ---------------------------------------------------------------------------
# DataClass
# ---------------------------------------------------------------------------


@dataclass
class WebsiteGapSignals:
    """Signals used to compute Dimension H (Website Gap Opportunity)."""

    has_website: bool          # from company.has_website (Places data)
    is_https: bool             # website URL starts with https://
    has_viewport: bool         # <meta name="viewport"> present in HTML
    copyright_year_age: int    # years since oldest copyright year found (0 = not found)
    has_social_links: bool     # any facebook/instagram/linkedin/twitter href found
    word_count: int            # total words across all saved pages

    @property
    def website_status(self) -> str:
        """Human-readable status string for export columns."""
        if not self.has_website:
            return "none"
        outdated = (
            not self.is_https
            or not self.has_viewport
            or self.copyright_year_age >= 3
        )
        return "outdated" if outdated else "present"

    @property
    def is_outdated(self) -> bool:
        """True when website exists but shows clear age/quality signals."""
        return self.has_website and self.website_status == "outdated"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_website_gap(company, pages: list, base_path: Path | None = None) -> WebsiteGapSignals:
    """Build :class:`WebsiteGapSignals` from company data and saved HTML pages.

    Args:
        company:    ORM Company instance — only ``.has_website`` and ``.website`` are read.
        pages:      List of CompanyPage ORM instances (may be empty for no-website companies).
        base_path:  Root directory where HTML files live (e.g. ``data/pages/``).
                    If None, page HTML is not read from disk.
    """
    has_website: bool = bool(company.has_website)
    website_url: str = company.website or ""
    is_https: bool = website_url.lower().startswith("https://")

    # For no-website companies there are no pages to analyse.
    if not has_website or not pages:
        return WebsiteGapSignals(
            has_website=has_website,
            is_https=False,
            has_viewport=False,
            copyright_year_age=0,
            has_social_links=False,
            word_count=0,
        )

    # --- Collect HTML from saved pages ---
    combined_html = ""
    total_words = 0
    for page in pages:
        if base_path and page.page_path:
            html_path = base_path / page.page_path
            try:
                combined_html += html_path.read_bytes().decode("utf-8", errors="ignore")
            except OSError:
                log.debug("website_gap: could not read %s", html_path)
        if page.word_count:
            total_words += page.word_count

    # --- Extract signals from HTML ---
    has_viewport = bool(_VIEWPORT_RE.search(combined_html))
    has_social_links = bool(_SOCIAL_RE.search(combined_html))

    # Find all copyright years and take the oldest one
    copyright_year_age = 0
    year_matches = _COPYRIGHT_RE.findall(combined_html)
    if year_matches:
        oldest_year = min(int(y) for y in year_matches)
        current_year = datetime.date.today().year
        copyright_year_age = max(0, current_year - oldest_year)

    return WebsiteGapSignals(
        has_website=has_website,
        is_https=is_https,
        has_viewport=has_viewport,
        copyright_year_age=copyright_year_age,
        has_social_links=has_social_links,
        word_count=total_words,
    )
