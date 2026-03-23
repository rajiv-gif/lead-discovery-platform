"""Discovery runner — orchestrates a full discovery run for a campaign.

Dispatches on ``campaign.discovery_source``:
  - GOOGLE_PLACES → Places API via ``_run_places_discovery()``
  - WEB_SEARCH    → DuckDuckGo via ``web_runner.run_web_discovery_for_campaign()``

Entry point: ``run_discovery_for_campaign(campaign_id)``

Places flow:
  1. Load campaign from DB.
  2. Build GeoQuery list via ``strategies.build_queries()``.
  3. For each query:
     a. Call ``PlacesClient.search()`` — catch ``PlacesAPIError``, log, continue.
     b. For each PlaceResult, upsert Company and create DiscoveryHit inside
        a shared session that commits once per query (not per result).
  4. Return a ``DiscoverySummary`` dataclass.

Cross-query deduplication: ``create_discovery_hit`` already skips duplicate
(campaign_id, source_url) pairs, so companies discovered in multiple cities
for a STATE campaign produce only one hit per company.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select

from src.config.settings import settings
from src.db.session import get_session
from src.discovery.places import PlacesAPIError, PlacesClient
from src.discovery.strategies import build_queries
from src.discovery.upsert import create_discovery_hit, upsert_company
from src.models.campaign import Campaign
from src.models.enums import DiscoverySource

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class DiscoverySummary:
    """Aggregated counters returned after a discovery run."""

    queries_run: int = 0
    total_results: int = 0
    companies_created: int = 0
    companies_matched: int = 0
    hits_created: int = 0
    hits_skipped: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_discovery_for_campaign(campaign_id: uuid.UUID) -> DiscoverySummary:
    """Run discovery for *campaign_id*, dispatching on discovery_source.

    Args:
        campaign_id: UUID of the campaign to process.

    Returns:
        A ``DiscoverySummary`` with counts for the run.

    Raises:
        ValueError: If the campaign does not exist in the database.
        RuntimeError: If a required API key is missing.
    """
    # Load campaign
    campaign: Optional[Campaign] = None
    with get_session() as session:
        campaign = session.execute(
            select(Campaign).where(Campaign.id == campaign_id)
        ).scalar_one_or_none()

        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found in the database.")

        session.expunge(campaign)

    source = campaign.discovery_source or DiscoverySource.GOOGLE_PLACES

    if source == DiscoverySource.WEB_SEARCH:
        from src.discovery.web_runner import run_web_discovery_for_campaign
        return run_web_discovery_for_campaign(campaign_id, campaign)

    return _run_places_discovery(campaign_id, campaign)


# ---------------------------------------------------------------------------
# Google Places discovery
# ---------------------------------------------------------------------------


def _run_places_discovery(
    campaign_id: uuid.UUID,
    campaign: Campaign,
) -> DiscoverySummary:
    """Run Google Places discovery for *campaign*."""
    if not settings.google_places_api_key:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY is not set. "
            "Add it to your .env file before running discovery."
        )

    log.info(
        "Starting Places discovery for campaign id=%s name=%r method=%s",
        campaign_id,
        campaign.name,
        campaign.geo_method,
    )

    client = PlacesClient(
        api_key=settings.google_places_api_key,
        rate_limit_delay=settings.places_rate_limit_delay,
        max_pages=settings.places_max_pages,
    )

    queries = build_queries(campaign)
    summary = DiscoverySummary()

    log.info("Built %d queries for campaign %s", len(queries), campaign_id)

    for query in queries:
        summary.queries_run += 1
        log.info("Running query %r (method=%s)", query.text_query, query.method)

        try:
            results = client.search(query)
        except PlacesAPIError as exc:
            summary.errors += 1
            detail = f"Query {query.text_query!r}: {exc}"
            summary.error_details.append(detail)
            log.error("Places API error: %s", detail)
            continue

        summary.total_results += len(results)
        log.info("Query returned %d results", len(results))

        # All upserts for this query share one session — commit once per query.
        with get_session() as session:
            for rank, result in enumerate(results):
                company, company_created = upsert_company(session, result)
                if company_created:
                    summary.companies_created += 1
                else:
                    summary.companies_matched += 1

                hit, hit_created = create_discovery_hit(
                    session=session,
                    campaign_id=campaign_id,
                    company=company,
                    result=result,
                    query=query,
                    rank=rank,
                )
                if hit_created:
                    summary.hits_created += 1
                else:
                    summary.hits_skipped += 1

    log.info(
        "Places discovery complete: queries=%d results=%d new=%d matched=%d errors=%d",
        summary.queries_run,
        summary.total_results,
        summary.companies_created,
        summary.companies_matched,
        summary.errors,
    )
    return summary
