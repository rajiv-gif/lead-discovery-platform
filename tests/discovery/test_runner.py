"""Unit tests for src/discovery/runner.py.

Tests use mocks for the database session, PlacesClient, and settings.
No live DB or API calls are made.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.discovery.places import PlacesAPIError, PlaceResult
from src.discovery.runner import DiscoverySummary, run_discovery_for_campaign
from src.models.enums import GeoMethod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CAMPAIGN_ID = uuid.uuid4()


def _make_place_result(place_id: str = "ChIJabc") -> PlaceResult:
    return PlaceResult(
        place_id=place_id,
        name="Test Dental",
        formatted_address="1 High St, London",
        website_uri="https://testdental.co.uk/",
        domain="testdental.co.uk",
    )


def _make_campaign(geo_method=GeoMethod.CITY):
    c = MagicMock()
    c.id = CAMPAIGN_ID
    c.name = "Test Campaign"
    c.geo_method = geo_method
    c.specialty = "dentists"
    c.geo_city = "London"
    c.geo_country = "UK"
    return c


# ---------------------------------------------------------------------------
# API key guard
# ---------------------------------------------------------------------------


@patch("src.discovery.runner.settings")
def test_missing_api_key_raises_runtime_error(mock_settings):
    mock_settings.google_places_api_key = None

    with pytest.raises(RuntimeError, match="GOOGLE_PLACES_API_KEY"):
        run_discovery_for_campaign(CAMPAIGN_ID)


# ---------------------------------------------------------------------------
# Campaign not found
# ---------------------------------------------------------------------------


@patch("src.discovery.runner.get_session")
@patch("src.discovery.runner.settings")
def test_missing_campaign_raises_value_error(mock_settings, mock_get_session):
    mock_settings.google_places_api_key = "test-key"
    mock_settings.places_rate_limit_delay = 0.0
    mock_settings.places_max_pages = 1

    # Simulate session returning None for the campaign lookup
    ctx = MagicMock()
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx

    with pytest.raises(ValueError, match="not found"):
        run_discovery_for_campaign(CAMPAIGN_ID)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@patch("src.discovery.runner.create_discovery_hit")
@patch("src.discovery.runner.upsert_company")
@patch("src.discovery.runner.PlacesClient")
@patch("src.discovery.runner.get_session")
@patch("src.discovery.runner.settings")
def test_successful_run_returns_summary(
    mock_settings, mock_get_session, MockPlacesClient,
    mock_upsert_company, mock_create_hit,
):
    mock_settings.google_places_api_key = "test-key"
    mock_settings.places_rate_limit_delay = 0.0
    mock_settings.places_max_pages = 1

    campaign = _make_campaign()
    company = MagicMock()

    # First session: campaign lookup
    load_ctx = MagicMock()
    load_session = MagicMock()
    load_session.execute.return_value.scalar_one_or_none.return_value = campaign
    load_ctx.__enter__ = MagicMock(return_value=load_session)
    load_ctx.__exit__ = MagicMock(return_value=False)

    # Second session: upsert
    upsert_ctx = MagicMock()
    upsert_session = MagicMock()
    upsert_ctx.__enter__ = MagicMock(return_value=upsert_session)
    upsert_ctx.__exit__ = MagicMock(return_value=False)

    mock_get_session.side_effect = [load_ctx, upsert_ctx]

    # PlacesClient returns 2 results
    MockPlacesClient.return_value.search.return_value = [
        _make_place_result("place1"),
        _make_place_result("place2"),
    ]
    mock_upsert_company.side_effect = [(company, True), (company, False)]
    mock_create_hit.side_effect = [(MagicMock(), True), (MagicMock(), True)]

    summary = run_discovery_for_campaign(CAMPAIGN_ID)

    assert isinstance(summary, DiscoverySummary)
    assert summary.queries_run == 1
    assert summary.total_results == 2
    assert summary.companies_created == 1
    assert summary.companies_matched == 1
    assert summary.hits_created == 2
    assert summary.hits_skipped == 0
    assert summary.errors == 0


@patch("src.discovery.runner.create_discovery_hit")
@patch("src.discovery.runner.upsert_company")
@patch("src.discovery.runner.PlacesClient")
@patch("src.discovery.runner.get_session")
@patch("src.discovery.runner.settings")
def test_places_api_error_is_captured_not_raised(
    mock_settings, mock_get_session, MockPlacesClient,
    mock_upsert_company, mock_create_hit,
):
    mock_settings.google_places_api_key = "test-key"
    mock_settings.places_rate_limit_delay = 0.0
    mock_settings.places_max_pages = 1

    campaign = _make_campaign()

    load_ctx = MagicMock()
    load_session = MagicMock()
    load_session.execute.return_value.scalar_one_or_none.return_value = campaign
    load_ctx.__enter__ = MagicMock(return_value=load_session)
    load_ctx.__exit__ = MagicMock(return_value=False)

    # No upsert session needed — error is captured before upsert
    mock_get_session.return_value = load_ctx

    MockPlacesClient.return_value.search.side_effect = PlacesAPIError("quota exceeded", 429)

    summary = run_discovery_for_campaign(CAMPAIGN_ID)

    assert summary.errors == 1
    assert len(summary.error_details) == 1
    assert "quota exceeded" in summary.error_details[0]
    # Runner did not propagate the exception
    assert summary.queries_run == 1
    assert summary.total_results == 0


@patch("src.discovery.runner.create_discovery_hit")
@patch("src.discovery.runner.upsert_company")
@patch("src.discovery.runner.PlacesClient")
@patch("src.discovery.runner.get_session")
@patch("src.discovery.runner.settings")
def test_hits_skipped_counted_correctly(
    mock_settings, mock_get_session, MockPlacesClient,
    mock_upsert_company, mock_create_hit,
):
    mock_settings.google_places_api_key = "test-key"
    mock_settings.places_rate_limit_delay = 0.0
    mock_settings.places_max_pages = 1

    campaign = _make_campaign()
    company = MagicMock()

    load_ctx = MagicMock()
    load_session = MagicMock()
    load_session.execute.return_value.scalar_one_or_none.return_value = campaign
    load_ctx.__enter__ = MagicMock(return_value=load_session)
    load_ctx.__exit__ = MagicMock(return_value=False)

    upsert_ctx = MagicMock()
    upsert_session = MagicMock()
    upsert_ctx.__enter__ = MagicMock(return_value=upsert_session)
    upsert_ctx.__exit__ = MagicMock(return_value=False)

    mock_get_session.side_effect = [load_ctx, upsert_ctx]

    MockPlacesClient.return_value.search.return_value = [_make_place_result("p1")]
    mock_upsert_company.return_value = (company, False)   # matched
    mock_create_hit.return_value = (MagicMock(), False)    # skipped (already exists)

    summary = run_discovery_for_campaign(CAMPAIGN_ID)

    assert summary.hits_skipped == 1
    assert summary.hits_created == 0
    assert summary.companies_matched == 1
    assert summary.companies_created == 0
