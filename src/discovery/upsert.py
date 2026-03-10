"""Company upsert and discovery-hit creation for the Places discovery stage.

Deduplication strategy for companies (in priority order):
  1. ``Company.google_place_id`` — stable, unique across the Places dataset.
  2. ``Company.domain``          — extracted from website; good cross-source key.
  3. INSERT new                  — no match found; treat as a previously unknown company.

Field-update semantics on match: "fill gaps only".
  - A core column is updated only when it is currently falsy (None or "").
  - ``extra_fields`` (JSONB) is always deep-merged; new data wins on overlap.

This conservative strategy avoids clobbering data that was manually curated
or sourced from a higher-quality provider.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.discovery.places import PlaceResult
from src.discovery.strategies import GeoQuery
from src.models.company import Company
from src.models.discovery_hit import DiscoveryHit
from src.models.enums import DiscoveryHitSourceType, DiscoveryHitStatus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Company upsert
# ---------------------------------------------------------------------------


def upsert_company(session: Session, result: PlaceResult) -> tuple[Company, bool]:
    """Find or create a ``Company`` row for *result*.

    Returns:
        ``(company, created)`` where ``created`` is True for new rows.
    """
    company: Optional[Company] = None

    # --- 1. Lookup by google_place_id ---
    company = session.execute(
        select(Company).where(Company.google_place_id == result.place_id)
    ).scalar_one_or_none()

    if company is not None:
        log.debug("company matched by google_place_id=%r", result.place_id)
        _merge_fields(company, result)
        return company, False

    # --- 2. Fallback: lookup by domain ---
    if result.domain:
        company = session.execute(
            select(Company).where(Company.domain == result.domain)
        ).scalar_one_or_none()

        if company is not None:
            log.debug(
                "company matched by domain=%r (place_id=%r)",
                result.domain,
                result.place_id,
            )
            # Backfill google_place_id now that we know it
            if not company.google_place_id:
                company.google_place_id = result.place_id
            _merge_fields(company, result)
            return company, False

    # --- 3. Create new ---
    extra = _build_extra_fields(result)
    company = Company(
        name=result.name,
        website=result.website_uri,
        domain=result.domain,
        google_place_id=result.place_id,
        address=result.formatted_address,
        city=result.city,
        state=result.state,
        country=result.country,
        extra_fields=extra,
    )
    session.add(company)
    # Flush so the ORM assigns an id before the caller creates a DiscoveryHit.
    session.flush()
    log.debug("company created: name=%r place_id=%r", result.name, result.place_id)
    return company, True


# ---------------------------------------------------------------------------
# Discovery hit creation
# ---------------------------------------------------------------------------


def create_discovery_hit(
    session: Session,
    campaign_id: object,  # uuid.UUID
    company: Company,
    result: PlaceResult,
    query: GeoQuery,
    rank: int,
) -> tuple[DiscoveryHit, bool]:
    """Find or create a ``DiscoveryHit`` for *result* within *campaign_id*.

    The canonical ``source_url`` for a Places result is the stable Maps URL
    built from the place_id.  This URL is guaranteed stable across re-runs
    and satisfies the ``UNIQUE(campaign_id, source_url)`` constraint.

    Returns:
        ``(hit, created)`` where ``created`` is True for new rows.
    """
    source_url = f"https://maps.google.com/maps?q=place_id:{result.place_id}"

    existing: Optional[DiscoveryHit] = session.execute(
        select(DiscoveryHit).where(
            DiscoveryHit.campaign_id == campaign_id,
            DiscoveryHit.source_url == source_url,
        )
    ).scalar_one_or_none()

    if existing is not None:
        log.debug(
            "discovery_hit already exists for campaign=%s place_id=%r",
            campaign_id,
            result.place_id,
        )
        return existing, False

    hit = DiscoveryHit(
        campaign_id=campaign_id,
        company_id=company.id,
        source_url=source_url,
        source_type=DiscoveryHitSourceType.GOOGLE_MAPS,
        status=DiscoveryHitStatus.PENDING,
        discovery_query=query.text_query,
        discovery_method=query.method,
        discovery_lat=query.center_lat,
        discovery_lng=query.center_lng,
        discovery_radius_m=query.radius_m,
        api_response_rank=rank,
        discovered_at=datetime.now(timezone.utc),
    )
    session.add(hit)
    return hit, True


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _merge_fields(company: Company, result: PlaceResult) -> None:
    """Fill empty fields on *company* from *result* and merge extra_fields."""
    if not company.name:
        company.name = result.name
    if not company.website and result.website_uri:
        company.website = result.website_uri
    if not company.domain and result.domain:
        company.domain = result.domain
    if not company.address and result.formatted_address:
        company.address = result.formatted_address
    if not company.city and result.city:
        company.city = result.city
    if not company.state and result.state:
        company.state = result.state
    if not company.country and result.country:
        company.country = result.country

    # Merge extra_fields: existing data wins on key conflicts.
    new_extra = _build_extra_fields(result)
    if company.extra_fields:
        # new_extra provides defaults; existing data overwrites.
        merged = {**new_extra, **company.extra_fields}
        company.extra_fields = merged
    else:
        company.extra_fields = new_extra


def _build_extra_fields(result: PlaceResult) -> dict:
    """Build the extra_fields dict from a Places result."""
    return {
        "phone": result.phone_number,
        "rating": result.rating,
        "user_rating_count": result.user_rating_count,
        "latitude": result.latitude,
        "longitude": result.longitude,
        "postal_code": result.postal_code,
        "business_status": result.business_status,
        "types": result.types,
        "country_code": result.country_code,
    }
