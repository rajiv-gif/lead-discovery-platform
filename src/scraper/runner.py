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
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.session import get_session
from src.models.company import Company
from src.models.discovery_hit import DiscoveryHit
from src.models.enums import CampaignGoal, DiscoveryHitStatus, PageType
from src.config.settings import settings as _settings
from src.scraper.classifier import classify_page
from src.scraper.fetcher import Fetcher, FetchResult, RobotCache
from src.scraper.page_finder import find_supplemental_urls
from src.scraper.persist import save_page
from src.scraper.playwright_fetcher import fetch_with_playwright, should_try_playwright

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


def _root_url(url: str) -> str | None:
    """Return the root homepage URL (scheme + netloc) for a deep URL.

    Returns None if the URL is already a root URL or cannot be parsed.
    e.g. 'https://example.com/about/team' → 'https://example.com'
         'https://example.com/' → None (already root)
    """
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if not path or path == "":
            return None  # already at root
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return None


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


def _scrape_shopify_store(
    session: Session,
    hit: DiscoveryHit,
    company: Company,
    fetcher: Fetcher,
    summary: ScrapeSummary,
) -> None:
    """Scrape a confirmed Shopify .myshopify.com store.

    Strategy (in order):
      1. Try ``<store>/pages/contact`` — static, rarely rate-limited, has email/phone/address.
      2. Try the store homepage (root .myshopify.com URL).
      3. Fall back to a synthetic HTML page built from /products.json metadata already
         in extra_fields — no network request, but also no contact info for the LLM.

    All three outcomes mark the hit as SCRAPED so the pipeline never gets stuck.
    """
    extra = company.extra_fields or {}
    myshopify_url = (extra.get("shopify_myshopify_url") or company.website or "").rstrip("/")
    product_count = extra.get("shopify_product_count") or 0
    price_min = extra.get("shopify_price_min") or 0
    price_max = extra.get("shopify_price_max") or 0
    domain = company.domain or urlparse(myshopify_url).netloc or myshopify_url

    # Derive root store URL from the myshopify backend URL
    parsed = urlparse(myshopify_url)
    root_store_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else myshopify_url

    # --- Attempt 1: /pages/contact ---
    contact_url = f"{root_store_url}/pages/contact"
    contact_result = fetcher.fetch(contact_url)
    if contact_result.ok:
        page, created = save_page(
            session=session,
            company_id=company.id,
            result=contact_result,
            page_type=PageType.CONTACT,
            discovery_hit_id=hit.id,
        )
        summary.pages_saved += 1 if created else 0
        summary.pages_deduplicated += 0 if created else 1
        hit.status = DiscoveryHitStatus.SCRAPED
        hit.error_message = None
        summary.hits_scraped += 1
        log.info("hit %s: Shopify contact page fetched for %r", hit.id, domain)
        return

    log.debug(
        "hit %s: /pages/contact failed for %r (%s) — trying homepage",
        hit.id, domain, contact_result.error,
    )

    # --- Attempt 2: store homepage ---
    home_result = fetcher.fetch(root_store_url)
    if home_result.ok:
        page, created = save_page(
            session=session,
            company_id=company.id,
            result=home_result,
            page_type=PageType.HOMEPAGE,
            discovery_hit_id=hit.id,
        )
        summary.pages_saved += 1 if created else 0
        summary.pages_deduplicated += 0 if created else 1
        hit.status = DiscoveryHitStatus.SCRAPED
        hit.error_message = None
        summary.hits_scraped += 1
        log.info("hit %s: Shopify homepage fetched for %r", hit.id, domain)
        return

    log.debug(
        "hit %s: homepage failed for %r (%s) — using synthetic fallback",
        hit.id, domain, home_result.error,
    )

    # --- Attempt 3: synthetic fallback ---
    html = (
        f"<html><head><title>{domain}</title></head><body>"
        f"<h1>{domain}</h1>"
        f"<p>Shopify ecommerce store with {product_count} products. "
        f"Price range: {price_min:.0f}–{price_max:.0f} EUR.</p>"
        f"<p>Store backend URL: {myshopify_url}</p>"
        f"<p>Website: {company.website}</p>"
        f"</body></html>"
    )
    result = FetchResult(
        url=root_store_url,
        final_url=root_store_url,
        html=html,
        status_code=200,
        content_type="text/html",
    )
    page, created = save_page(
        session=session,
        company_id=company.id,
        result=result,
        page_type=PageType.HOMEPAGE,
        discovery_hit_id=hit.id,
    )
    summary.pages_saved += 1 if created else 0
    summary.pages_deduplicated += 0 if created else 1
    hit.status = DiscoveryHitStatus.SCRAPED
    hit.error_message = None
    summary.hits_scraped += 1
    log.info(
        "hit %s: synthetic Shopify fallback for %r (%d products, %.0f–%.0f EUR)",
        hit.id, domain, product_count, price_min, price_max,
    )


def _playwright_fallback(url: str, result: FetchResult) -> FetchResult:
    """Try Playwright if enabled and the HTTP result warrants it."""
    if not _settings.playwright_enabled:
        return result
    if not should_try_playwright(result):
        return result
    log.info("HTTP fetch struggled for %r (%s) — retrying with Playwright", url, result.error or result.status_code)
    pw_result = fetch_with_playwright(url, timeout=_settings.playwright_timeout)
    if pw_result.ok:
        log.info("Playwright succeeded for %r (%d bytes)", url, len(pw_result.html))
        return pw_result
    log.debug("Playwright also failed for %r — %s", url, pw_result.error)
    return result  # return original; caller handles failure


def _scrape_hit(
    session: Session,
    hit: DiscoveryHit,
    company: Company,
    fetcher: Fetcher,
    summary: ScrapeSummary,
    campaign_goal: CampaignGoal = CampaignGoal.LEAD_GEN,
) -> None:
    """Scrape all pages for one ``DiscoveryHit`` in-place, updating *summary*."""
    # WEB_AGENCY short-circuit: businesses with no website need no scraping.
    # Mark them SCRAPED immediately so they continue to verification → scoring
    # where the website-gap dimension rewards them.
    if not company.has_website and campaign_goal == CampaignGoal.WEB_AGENCY:
        log.info(
            "hit %s: no website (web_agency campaign) — fast-pathing to scraped",
            hit.id,
        )
        hit.status = DiscoveryHitStatus.SCRAPED
        summary.hits_scraped += 1
        return

    # Confirmed Shopify .myshopify.com stores: use the dedicated Shopify scraper
    # that tries /pages/contact → homepage → synthetic fallback, avoiding the deep
    # product-page URLs that Shopify CDN aggressively rate-limits (429).
    extra = company.extra_fields or {}
    website_host = urlparse(company.website or "").netloc.lower()
    if extra.get("platform") == "shopify" and website_host.endswith(".myshopify.com"):
        _scrape_shopify_store(session, hit, company, fetcher, summary)
        return

    website = company.website
    if not website:
        log.info("hit %s: company %s has no website — skipping", hit.id, company.id)
        hit.status = DiscoveryHitStatus.SKIPPED
        summary.hits_skipped += 1
        return

    # --- Fetch homepage ---
    homepage_result: FetchResult = fetcher.fetch(website)
    homepage_result = _playwright_fallback(website, homepage_result)

    if not homepage_result.ok:
        # Deep URL failed — try the root domain before giving up.
        # Serper often returns sub-pages (e.g. /about/, /services/) that block
        # scraping while the root homepage is accessible.
        root = _root_url(website)
        if root:
            log.info(
                "hit %s: deep URL %r failed (%s) — trying root %r",
                hit.id, website, homepage_result.error, root,
            )
            homepage_result = fetcher.fetch(root)
            homepage_result = _playwright_fallback(root, homepage_result)
            if homepage_result.ok:
                # Update stored website to root so future runs go straight there
                company.website = root
                website = root
                log.info("hit %s: root fallback succeeded for %r", hit.id, root)

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
        sup_result = _playwright_fallback(sup_url, sup_result)
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
                _scrape_hit(session, hit, company, fetcher, summary, campaign.campaign_goal)
            except Exception as exc:
                log.exception("hit %s: unexpected error", hit.id)
                hit.status = DiscoveryHitStatus.FAILED
                hit.error_message = str(exc)
                summary.hits_failed += 1
                summary.record_error(f"hit={hit.id}: {exc}")

    return summary
