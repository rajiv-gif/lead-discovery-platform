"""Scrape runner for Phase 2.

For each ``DiscoveryHit`` with status ``pending`` belonging to the given
campaign, the runner:

  1. Identifies the company's website URL.
  2. Fetches the homepage.
  3. Discovers supplemental pages (ABOUT → CONTACT → TEAM; SERVICES/OTHER fallbacks).
  4. Fetches each supplemental page.
  5. Persists all successfully-fetched pages via ``save_page()``.
  6. Transitions the hit status to ``scraped`` (all ok) or ``failed``.

Hits without a company or website are skipped (status → skipped).

Status transitions
------------------
  pending  →  scraped   (homepage fetched OK; may have partial supplemental)
  pending  →  failed    (homepage fetch failed or HTTP error)
  pending  →  skipped   (no company, no website, or domain suppressed)

``ScrapeSummary`` aggregates counts for CLI reporting.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.session import get_session
from src.models.company import Company
from src.models.discovery_hit import DiscoveryHit
from src.models.enums import DiscoveryHitStatus, PageType
from src.scraper.classifier import classify_page
from src.scraper.fetcher import Fetcher, FetchResult, RobotCache
from src.scraper.page_finder import find_supplemental_urls
from src.scraper.persist import save_page

log = logging.getLogger(__name__)

# PageType priority order for supplemental page selection
_SUPPLEMENTAL_PRIORITY: list[PageType] = [
    PageType.ABOUT,
    PageType.CONTACT,
    PageType.TEAM,
    PageType.SERVICES,
    PageType.OTHER,
]


# ---------------------------------------------------------------------------
# ScrapeSummary
# ---------------------------------------------------------------------------


@dataclass
class ScrapeSummary:
    hits_scraped: int = 0
    hits_skipped: int = 0
    hits_failed: int = 0
    pages_saved: int = 0
    pages_deduplicated: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def record_error(self, detail: str) -> None:
        self.errors += 1
        self.error_details.append(detail)


# ---------------------------------------------------------------------------
# Title / H1 extraction helper
# ---------------------------------------------------------------------------


def _extract_title_h1(html: str) -> tuple[str | None, str | None]:
    """Return (title_text, first_h1_text) from *html* using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None
        h1_tag = soup.find("h1")
        h1 = h1_tag.get_text(strip=True) if h1_tag else None
        return title, h1
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Per-hit scrape logic
# ---------------------------------------------------------------------------


def _scrape_hit(
    session: Session,
    hit: DiscoveryHit,
    company: Company,
    fetcher: Fetcher,
    summary: ScrapeSummary,
) -> None:
    """Scrape all pages for one ``DiscoveryHit`` in-place, updating *summary*."""
    website = company.website
    if not website:
        log.info("hit %s: company %s has no website — skipping", hit.id, company.id)
        hit.status = DiscoveryHitStatus.SKIPPED
        summary.hits_skipped += 1
        return

    # --- Fetch homepage ---
    homepage_result: FetchResult = fetcher.fetch(website)

    if not homepage_result.ok:
        log.warning(
            "hit %s: homepage fetch failed for %r — %s",
            hit.id, website, homepage_result.error,
        )
        hit.status = DiscoveryHitStatus.FAILED
        hit.error_message = homepage_result.error or f"HTTP {homepage_result.status_code}"
        summary.hits_failed += 1
        summary.record_error(f"hit={hit.id} url={website}: {hit.error_message}")
        return

    # Persist homepage
    page, created = save_page(
        session=session,
        company_id=company.id,
        result=homepage_result,
        page_type=PageType.HOMEPAGE,
        discovery_hit_id=hit.id,
    )
    if created:
        summary.pages_saved += 1
    else:
        summary.pages_deduplicated += 1

    # --- Discover and fetch supplemental pages ---
    supplemental = find_supplemental_urls(homepage_result.final_url, homepage_result.html)

    for page_type in _SUPPLEMENTAL_PRIORITY:
        sup_url = supplemental.get(page_type)
        if not sup_url:
            continue

        sup_result = fetcher.fetch(sup_url)
        if not sup_result.ok:
            log.debug(
                "hit %s: supplemental %s fetch failed for %r — %s",
                hit.id, page_type.value, sup_url, sup_result.error,
            )
            continue  # Non-fatal — partial supplemental is acceptable

        # Reclassify using title + H1 for precision
        title, h1 = _extract_title_h1(sup_result.html)
        classified_type = classify_page(sup_url, title, h1)

        sup_page, sup_created = save_page(
            session=session,
            company_id=company.id,
            result=sup_result,
            page_type=classified_type,
            discovery_hit_id=hit.id,
        )
        if sup_created:
            summary.pages_saved += 1
        else:
            summary.pages_deduplicated += 1

    hit.status = DiscoveryHitStatus.SCRAPED
    hit.error_message = None
    summary.hits_scraped += 1


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_scrape_for_campaign(campaign_id: uuid.UUID) -> ScrapeSummary:
    """Scrape all pending hits for *campaign_id*.

    Raises:
        ValueError: If no campaign with *campaign_id* exists.
    """
    summary = ScrapeSummary()
    robot_cache = RobotCache()
    fetcher = Fetcher(robot_cache=robot_cache)

    with get_session() as session:
        # Verify campaign exists
        from src.models.campaign import Campaign
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        # Load all pending hits with their companies eagerly
        hits: list[DiscoveryHit] = list(
            session.execute(
                select(DiscoveryHit).where(
                    DiscoveryHit.campaign_id == campaign_id,
                    DiscoveryHit.status == DiscoveryHitStatus.PENDING,
                )
            ).scalars()
        )

        log.info("scrape: found %d pending hits for campaign %s", len(hits), campaign_id)

        for hit in hits:
            if hit.company_id is None:
                log.info("hit %s: no company assigned — skipping", hit.id)
                hit.status = DiscoveryHitStatus.SKIPPED
                summary.hits_skipped += 1
                continue

            company: Optional[Company] = session.get(Company, hit.company_id)
            if company is None:
                log.warning("hit %s: company %s not found — skipping", hit.id, hit.company_id)
                hit.status = DiscoveryHitStatus.SKIPPED
                summary.hits_skipped += 1
                continue

            try:
                _scrape_hit(session, hit, company, fetcher, summary)
            except Exception as exc:
                log.exception("hit %s: unexpected error", hit.id)
                hit.status = DiscoveryHitStatus.FAILED
                hit.error_message = str(exc)
                summary.hits_failed += 1
                summary.record_error(f"hit={hit.id}: {exc}")

    return summary
