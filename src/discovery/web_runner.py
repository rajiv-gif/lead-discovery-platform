"""Web-search discovery runner for ecommerce campaigns.

Uses DuckDuckGo to find company websites from free-text search queries stored
in ``campaign.search_queries``.  Each query returns up to 10 organic results;
companies are deduplicated by domain across all queries in the run.

Shopify platform mode (campaign.ecommerce_platform == "shopify"):
  - Appends '"cdn.shopify.com"' to all queries so search engines surface stores
    on custom domains (paid plans) as well as free *.myshopify.com stores
  - HTML fingerprint check (detect_shopify) filters out false positives before
    any enrichment is attempted
  - Fetches /products.json after discovery to enrich company.extra_fields with
    product count and price range (used in scoring + dashboard display)

The rest of the pipeline (scraper → extraction → scoring) is identical to the
Places flow — only the discovery source changes.
"""
from __future__ import annotations

import logging
import uuid

import httpx

from src.db.session import get_session
from src.discovery.runner import DiscoverySummary
from src.discovery.shopify import detect_shopify, enrich_company_extra_fields, fetch_shopify_info, extract_myshopify_url
from src.discovery.upsert import create_web_search_hit, upsert_company_from_web_search
from src.discovery.web_search import DuckDuckGoClient, WebSearchError
from src.models.campaign import Campaign

log = logging.getLogger(__name__)

_DDG_RATE_LIMIT = 2.0   # seconds between DDG requests
_MAX_RESULTS = 30        # organic results per query (fetches up to 3 DDG pages)
_HOMEPAGE_TIMEOUT = 10.0 # seconds to fetch homepage for Shopify detection


def run_web_discovery_for_campaign(
    campaign_id: uuid.UUID,
    campaign: Campaign,
) -> DiscoverySummary:
    """Run DuckDuckGo web-search discovery for *campaign*.

    Args:
        campaign_id: UUID of the campaign.
        campaign: Detached Campaign ORM object (already loaded by the caller).

    Returns:
        A ``DiscoverySummary`` with counts for the run.

    Raises:
        ValueError: If ``campaign.search_queries`` is empty.
    """
    is_shopify = (campaign.ecommerce_platform or "").lower() == "shopify"
    raw_queries: list[str] = campaign.search_queries or []

    if not raw_queries:
        raise ValueError(
            f"Campaign {campaign_id}: search_queries must have at least one entry "
            "for WEB_SEARCH discovery."
        )

    # For Shopify mode, append the CDN signal so search engines surface stores
    # on custom domains (paid plans) as well as free *.myshopify.com stores.
    queries = (
        [f'{q} "cdn.shopify.com"' for q in raw_queries]
        if is_shopify else raw_queries
    )

    log.info(
        "Starting web-search discovery for campaign id=%s name=%r (%d queries, platform=%s)",
        campaign_id,
        campaign.name,
        len(queries),
        campaign.ecommerce_platform or "any",
    )

    client = DuckDuckGoClient(rate_limit_delay=_DDG_RATE_LIMIT)
    summary = DiscoverySummary()
    seen_domains: set[str] = set()

    for query in queries:
        summary.queries_run += 1
        log.info("Web search query %r", query)

        try:
            results = client.search(query, max_results=_MAX_RESULTS)
        except WebSearchError as exc:
            summary.errors += 1
            detail = f"Query {query!r}: {exc}"
            summary.error_details.append(detail)
            log.error("Web search error: %s", detail)
            continue

        summary.total_results += len(results)
        log.info("Query %r → %d results", query, len(results))

        with get_session() as session:
            for rank, result in enumerate(results):
                # Cross-query dedup by domain within this run
                if result.domain in seen_domains:
                    summary.hits_skipped += 1
                    log.debug("Skipping duplicate domain %r", result.domain)
                    continue
                seen_domains.add(result.domain)

                # For Shopify mode: verify + enrich via products.json
                extra_fields: dict = {}
                if is_shopify:
                    extra_fields = _enrich_shopify(result.url, result.domain)

                company, company_created = upsert_company_from_web_search(
                    session=session,
                    url=result.url,
                    domain=result.domain,
                    name="",
                    title=result.title,
                    snippet=result.snippet,
                    extra_fields=extra_fields,
                )
                if company_created:
                    summary.companies_created += 1
                else:
                    # Merge Shopify info into existing company
                    if extra_fields and company.extra_fields:
                        company.extra_fields = {**company.extra_fields, **extra_fields}
                    elif extra_fields:
                        company.extra_fields = extra_fields
                    summary.companies_matched += 1

                hit, hit_created = create_web_search_hit(
                    session=session,
                    campaign_id=campaign_id,
                    company=company,
                    url=result.url,
                    query=query,
                    rank=rank,
                )
                if hit_created:
                    summary.hits_created += 1
                else:
                    summary.hits_skipped += 1

    log.info(
        "Web discovery complete: queries=%d results=%d new=%d matched=%d skipped=%d errors=%d",
        summary.queries_run,
        summary.total_results,
        summary.companies_created,
        summary.companies_matched,
        summary.hits_skipped,
        summary.errors,
    )
    return summary


def _enrich_shopify(url: str, domain: str) -> dict:
    """Fetch homepage and products.json, return Shopify enrichment dict.

    Returns an empty dict if the page doesn't pass the Shopify HTML fingerprint
    check — this filters out false positives from open-web search results.
    """
    extra: dict = {}
    try:
        resp = httpx.get(
            url,
            timeout=_HOMEPAGE_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "LeadDiscoveryBot/1.0"},
        )
        html = resp.text

        if not detect_shopify(html):
            log.debug("Shopify fingerprint not found for %r — skipping", domain)
            return {}

        myshopify_url = extract_myshopify_url(html, url)
        info = fetch_shopify_info(domain, myshopify_url)

        extra["platform"] = "shopify"
        if myshopify_url:
            extra["shopify_myshopify_url"] = myshopify_url
        if info.product_count:
            extra["shopify_product_count"] = info.product_count
        if info.price_min is not None:
            extra["shopify_price_min"] = info.price_min
        if info.price_max is not None:
            extra["shopify_price_max"] = info.price_max

        log.debug(
            "Shopify enrichment: domain=%r products=%d price=%.0f–%.0f",
            domain,
            info.product_count,
            info.price_min or 0,
            info.price_max or 0,
        )
    except Exception as exc:
        log.debug("Shopify enrichment failed for %r: %s", domain, exc)
        # Don't mark as shopify if we couldn't fetch the page — can't confirm.

    return extra
