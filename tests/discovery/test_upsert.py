"""Unit tests for src/discovery/upsert.py.

Uses MagicMock for SQLAlchemy session — no live DB required.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from src.discovery.places import PlaceResult
from src.discovery.strategies import GeoQuery
from src.discovery.upsert import _build_extra_fields, create_discovery_hit, upsert_company
from src.models.enums import DiscoveryHitSourceType, DiscoveryHitStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_result(**kwargs) -> PlaceResult:
    defaults = {
        "place_id": "ChIJabc",
        "name": "Smile Dental",
        "formatted_address": "1 Main St, London",
        "website_uri": "https://smiledental.co.uk/",
        "domain": "smiledental.co.uk",
        "phone_number": "+44 20 1234 5678",
        "rating": 4.5,
        "user_rating_count": 100,
        "latitude": 51.5,
        "longitude": -0.12,
        "city": "London",
        "state": "Greater London",
        "country": "United Kingdom",
        "country_code": "GB",
        "postal_code": "EC1A 1BB",
        "business_status": "OPERATIONAL",
        "types": ["dentist"],
        "raw": {},
    }
    defaults.update(kwargs)
    return PlaceResult(**defaults)


def make_query(**kwargs) -> GeoQuery:
    defaults = {
        "text_query": "dentists in London, UK",
        "location_restriction": None,
        "method": "city",
        "center_lat": None,
        "center_lng": None,
        "radius_m": None,
    }
    defaults.update(kwargs)
    return GeoQuery(**defaults)


def make_session(place_id_match=None, domain_match=None, hit_match=None) -> MagicMock:
    """Return a mock session whose execute().scalar_one_or_none() cycles through given values."""
    session = MagicMock()

    # Build a side_effect list for consecutive scalar_one_or_none calls
    side_effects = []
    if place_id_match is not None or domain_match is not None or hit_match is not None:
        # upsert_company calls
        side_effects.append(place_id_match)
        if domain_match is not None:
            side_effects.append(domain_match)
        if hit_match is not None:
            side_effects.append(hit_match)
    else:
        side_effects = [None, None, None]  # default: all misses

    call_count = [0]

    def _scalar():
        idx = call_count[0]
        call_count[0] += 1
        return side_effects[idx] if idx < len(side_effects) else None

    session.execute.return_value.scalar_one_or_none.side_effect = _scalar
    return session


# ---------------------------------------------------------------------------
# upsert_company — dedup
# ---------------------------------------------------------------------------


def test_upsert_creates_new_company_when_no_match():
    result = make_result()
    session = make_session()  # both lookups return None

    company, created = upsert_company(session, result)

    assert created is True
    session.add.assert_called_once()
    session.flush.assert_called_once()
    # Verify basic field assignment
    added = session.add.call_args[0][0]
    assert added.name == "Smile Dental"
    assert added.google_place_id == "ChIJabc"
    assert added.domain == "smiledental.co.uk"


def test_upsert_creates_new_company_returns_company():
    session = make_session()
    company, created = upsert_company(session, make_result())
    assert company is session.add.call_args[0][0]


def test_upsert_matches_existing_by_place_id():
    existing = MagicMock()
    existing.google_place_id = "ChIJabc"
    existing.name = "Smile Dental"
    existing.extra_fields = {}

    # First scalar returns the existing company (place_id match)
    session = make_session(place_id_match=existing)

    company, created = upsert_company(session, make_result())

    assert created is False
    assert company is existing
    session.add.assert_not_called()


def test_upsert_matches_existing_by_domain_when_no_place_id():
    existing_by_domain = MagicMock()
    existing_by_domain.google_place_id = None
    existing_by_domain.name = "Smile Dental"
    existing_by_domain.extra_fields = {}

    # place_id miss (None), then domain hit
    session = make_session(place_id_match=None, domain_match=existing_by_domain)

    company, created = upsert_company(session, make_result())

    assert created is False
    assert company is existing_by_domain
    session.add.assert_not_called()


def test_upsert_backfills_google_place_id_on_domain_match():
    existing = MagicMock()
    existing.google_place_id = None
    existing.name = "Smile Dental"
    existing.extra_fields = {}

    session = make_session(place_id_match=None, domain_match=existing)
    upsert_company(session, make_result(place_id="ChIJnew"))

    assert existing.google_place_id == "ChIJnew"


def test_upsert_skips_domain_lookup_when_domain_is_none():
    result = make_result(domain=None)
    session = make_session()

    upsert_company(session, result)

    # Only one execute call — no domain lookup
    assert session.execute.call_count == 1


# ---------------------------------------------------------------------------
# upsert_company — field merge
# ---------------------------------------------------------------------------


def test_upsert_fills_missing_fields_on_match():
    existing = MagicMock()
    existing.google_place_id = "ChIJabc"
    existing.name = "Smile Dental"
    existing.city = None
    existing.country = None
    existing.extra_fields = {}

    session = make_session(place_id_match=existing)
    upsert_company(session, make_result(city="London", country="United Kingdom"))

    assert existing.city == "London"
    assert existing.country == "United Kingdom"


def test_upsert_does_not_overwrite_existing_non_empty_fields():
    existing = MagicMock()
    existing.google_place_id = "ChIJabc"
    existing.name = "Smile Dental"
    existing.city = "Manchester"  # already set
    existing.country = "United Kingdom"
    existing.extra_fields = {}

    session = make_session(place_id_match=existing)
    upsert_company(session, make_result(city="London"))  # Places says London

    # Not overwritten
    assert existing.city == "Manchester"


def test_upsert_merges_extra_fields():
    existing = MagicMock()
    existing.google_place_id = "ChIJabc"
    existing.name = "Smile Dental"
    existing.city = "London"
    existing.extra_fields = {"custom_key": "preserved", "rating": 3.0}

    session = make_session(place_id_match=existing)
    upsert_company(session, make_result(rating=4.5))

    # custom_key preserved; existing rating wins over new (existing takes precedence)
    assert existing.extra_fields["custom_key"] == "preserved"
    # The merge strategy: new_extra is base, existing overwrites on conflict
    assert existing.extra_fields["rating"] == 3.0  # existing wins


# ---------------------------------------------------------------------------
# create_discovery_hit
# ---------------------------------------------------------------------------


CAMPAIGN_ID = uuid.uuid4()


def make_company_mock() -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    return c


def test_create_discovery_hit_creates_new():
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None  # no existing hit

    company = make_company_mock()
    result = make_result(place_id="ChIJhit")
    query = make_query()

    hit, created = create_discovery_hit(session, CAMPAIGN_ID, company, result, query, rank=3)

    assert created is True
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.source_url == "https://maps.google.com/maps?q=place_id:ChIJhit"
    assert added.source_type == DiscoveryHitSourceType.GOOGLE_MAPS
    assert added.status == DiscoveryHitStatus.PENDING
    assert added.api_response_rank == 3
    assert added.discovery_query == "dentists in London, UK"
    assert added.discovery_method == "city"
    assert added.campaign_id == CAMPAIGN_ID
    assert added.company_id == company.id


def test_create_discovery_hit_returns_existing_without_duplicate():
    existing_hit = MagicMock()
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = existing_hit

    hit, created = create_discovery_hit(
        session, CAMPAIGN_ID, make_company_mock(), make_result(), make_query(), rank=0
    )

    assert created is False
    assert hit is existing_hit
    session.add.assert_not_called()


def test_create_discovery_hit_sets_discovered_at():
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    hit, _ = create_discovery_hit(
        session, CAMPAIGN_ID, make_company_mock(), make_result(), make_query(), rank=0
    )

    added = session.add.call_args[0][0]
    assert isinstance(added.discovered_at, datetime)
    assert added.discovered_at.tzinfo is not None


def test_create_discovery_hit_canonical_source_url():
    """Source URL is always built from place_id, not the website URL."""
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    result = make_result(place_id="ChIJunique99")
    hit, _ = create_discovery_hit(
        session, CAMPAIGN_ID, make_company_mock(), result, make_query(), rank=0
    )
    added = session.add.call_args[0][0]
    assert added.source_url == "https://maps.google.com/maps?q=place_id:ChIJunique99"


def test_create_discovery_hit_stores_geo_coords():
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    query = make_query(method="center_radius", center_lat=51.5, center_lng=-0.12, radius_m=5000)
    hit, _ = create_discovery_hit(
        session, CAMPAIGN_ID, make_company_mock(), make_result(), query, rank=0
    )
    added = session.add.call_args[0][0]
    assert added.discovery_lat == 51.5
    assert added.discovery_lng == -0.12
    assert added.discovery_radius_m == 5000


# ---------------------------------------------------------------------------
# _build_extra_fields — None filtering
# ---------------------------------------------------------------------------


def test_build_extra_fields_excludes_none_values():
    """Keys whose PlaceResult value is None must not appear in extra_fields."""
    result = make_result(
        phone_number=None,
        rating=None,
        user_rating_count=None,
        postal_code=None,
        country_code=None,
    )
    extra = _build_extra_fields(result)

    assert "phone" not in extra
    assert "rating" not in extra
    assert "user_rating_count" not in extra
    assert "postal_code" not in extra
    assert "country_code" not in extra


def test_build_extra_fields_includes_present_values():
    """Keys with non-None values must be present in extra_fields."""
    result = make_result(
        rating=4.5,
        user_rating_count=100,
        business_status="OPERATIONAL",
    )
    extra = _build_extra_fields(result)

    assert extra["rating"] == 4.5
    assert extra["user_rating_count"] == 100
    assert extra["business_status"] == "OPERATIONAL"


def test_build_extra_fields_keeps_empty_list_for_types():
    """An empty types list is a valid value and must not be filtered out."""
    result = make_result(types=[])
    extra = _build_extra_fields(result)
    # types=[] is falsy but not None — must be retained
    assert "types" in extra
    assert extra["types"] == []
