"""Web-search discovery runner for ecommerce campaigns.

Uses DuckDuckGo to find company websites from free-text search queries stored
in ``campaign.search_queries``.  Each query returns up to 10 organic results;
companies are deduplicated by domain across all queries in the run.

The rest of the pipeline (scraper → extraction → scoring) is identical to the
Places flow — only the discovery source changes.
"""
from __future__ import annotations

import logging
import uuid

from src.db.session import get_session
from src.discovery.runner import DiscoverySummary
from src.discovery.upsert import create_web_search_hit, upsert_company_from_web_search
from src.discovery.web_search import DuckDuckGoClient, WebSearchError
from src.models.campaign import Campaign

log = logging.getLogger(__name__)

_DDG_RATE_LIMIT = 2.0   # seconds between DDG requests
_MAX_RESULTS = 10        # organic results per query


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
    queries: list[str] = campaign.search_queries or []
    if not queries:
        raise ValueError(
            f"Campaign {campaign_id}: search_queries must have at least one entry "
            "for WEB_SEARCH discovery."
        )

    log.info(
        "Starting web-search discovery for campaign id=%s name=%r (%d queries)",
        campaign_id,
        campaign.name,
        len(queries),
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

                company, company_created = upsert_company_from_web_search(
                    session=session,
                    url=result.url,
                    domain=result.domain,
                    name="",
                    title=result.title,
                    snippet=result.snippet,
                )
                if company_created:
                    summary.companies_created += 1
                else:
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
