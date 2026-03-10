"""Unit tests for src/cli.py — discovery-related commands.

Uses Typer's CliRunner for end-to-end command invocation without a live DB.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(*args: str):
    """Invoke ``leads`` CLI with the given arguments and return the result."""
    return runner.invoke(app, list(args))


# ---------------------------------------------------------------------------
# create-campaign — geo method validation
# ---------------------------------------------------------------------------


def test_create_campaign_invalid_geo_method_exits_1():
    result = _run("create-campaign", "Test", "--geo-method", "invalid_method")
    assert result.exit_code == 1
    assert "invalid" in result.output.lower() or "valid" in result.output.lower()


def test_create_campaign_city_missing_city_exits_1():
    result = _run(
        "create-campaign", "Test",
        "--geo-method", "city",
        "--country", "UK",
        # --city omitted
    )
    assert result.exit_code == 1


def test_create_campaign_city_missing_country_exits_1():
    result = _run(
        "create-campaign", "Test",
        "--geo-method", "city",
        "--city", "London",
        # --country omitted
    )
    assert result.exit_code == 1


def test_create_campaign_postal_code_missing_code_exits_1():
    result = _run("create-campaign", "Test", "--geo-method", "postal_code")
    assert result.exit_code == 1


def test_create_campaign_bounding_box_missing_coords_exits_1():
    result = _run(
        "create-campaign", "Test",
        "--geo-method", "bounding_box",
        "--sw-lat", "51.4",
        # missing sw-lng, ne-lat, ne-lng
    )
    assert result.exit_code == 1


def test_create_campaign_center_radius_missing_radius_exits_1():
    result = _run(
        "create-campaign", "Test",
        "--geo-method", "center_radius",
        "--center-lat", "51.5",
        "--center-lng", "-0.12",
        # missing --radius-m
    )
    assert result.exit_code == 1


def test_create_campaign_center_radius_zero_radius_exits_1():
    result = _run(
        "create-campaign", "Test",
        "--geo-method", "center_radius",
        "--center-lat", "51.5",
        "--center-lng", "-0.12",
        "--radius-m", "0",
    )
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# create-campaign — happy path (DB mocked)
# ---------------------------------------------------------------------------


@patch("src.cli.get_session")
def test_create_campaign_city_mode_succeeds(mock_get_session):
    campaign_id = uuid.uuid4()
    mock_campaign = MagicMock()
    mock_campaign.id = campaign_id

    ctx = MagicMock()
    session = MagicMock()
    session.flush.side_effect = lambda: setattr(mock_campaign, "id", campaign_id)
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx

    # Patch Campaign constructor to return our mock
    with patch("src.cli.Campaign", return_value=mock_campaign):
        result = _run(
            "create-campaign", "London Dentists",
            "--geo-method", "city",
            "--city", "London",
            "--country", "UK",
        )

    assert result.exit_code == 0
    assert "Campaign created" in result.output
    assert "city" in result.output
    assert "dentists" in result.output


@patch("src.cli.get_session")
def test_create_campaign_prints_run_discovery_hint(mock_get_session):
    mock_campaign = MagicMock()
    mock_campaign.id = uuid.uuid4()

    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx

    with patch("src.cli.Campaign", return_value=mock_campaign):
        result = _run(
            "create-campaign", "Test",
            "--geo-method", "city",
            "--city", "London",
            "--country", "UK",
        )

    assert "run-discovery" in result.output


# ---------------------------------------------------------------------------
# run-discovery — UUID validation
# ---------------------------------------------------------------------------


def test_run_discovery_invalid_uuid_exits_1():
    result = _run("run-discovery", "--campaign-id", "not-a-uuid")
    assert result.exit_code == 1
    assert "valid UUID" in result.output or "not a valid" in result.output.lower()


# ---------------------------------------------------------------------------
# run-discovery — missing API key
# ---------------------------------------------------------------------------


@patch("src.cli.run_discovery_for_campaign")
def test_run_discovery_missing_api_key_exits_1(mock_runner):
    mock_runner.side_effect = RuntimeError("GOOGLE_PLACES_API_KEY is not set")

    result = _run("run-discovery", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 1
    assert "GOOGLE_PLACES_API_KEY" in result.output


# ---------------------------------------------------------------------------
# run-discovery — campaign not found
# ---------------------------------------------------------------------------


@patch("src.cli.run_discovery_for_campaign")
def test_run_discovery_campaign_not_found_exits_1(mock_runner):
    mock_runner.side_effect = ValueError("Campaign abc-123 not found")

    result = _run("run-discovery", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# run-discovery — summary output
# ---------------------------------------------------------------------------


@patch("src.cli.run_discovery_for_campaign")
def test_run_discovery_prints_summary_table(mock_runner):
    from src.discovery.runner import DiscoverySummary

    mock_runner.return_value = DiscoverySummary(
        queries_run=2,
        total_results=35,
        companies_created=28,
        companies_matched=7,
        hits_created=35,
        hits_skipped=0,
        errors=0,
    )

    result = _run("run-discovery", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 0
    assert "Discovery complete" in result.output
    assert "35" in result.output   # total_results
    assert "28" in result.output   # companies_created


@patch("src.cli.run_discovery_for_campaign")
def test_run_discovery_with_errors_exits_1(mock_runner):
    from src.discovery.runner import DiscoverySummary

    mock_runner.return_value = DiscoverySummary(
        queries_run=1,
        total_results=0,
        companies_created=0,
        companies_matched=0,
        hits_created=0,
        hits_skipped=0,
        errors=1,
        error_details=["Query 'dentists in London, UK': HTTP 429 quota exceeded"],
    )

    result = _run("run-discovery", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 1
    assert "quota exceeded" in result.output or "Errors" in result.output
