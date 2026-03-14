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


def test_create_campaign_center_radius_radius_too_large_exits_1():
    """radius_m > 50,000 must be rejected with exit 1 (Places API maximum)."""
    result = _run(
        "create-campaign", "Test",
        "--geo-method", "center_radius",
        "--center-lat", "51.5",
        "--center-lng", "-0.12",
        "--radius-m", "50001",
    )
    assert result.exit_code == 1
    assert "50,000" in result.output or "50000" in result.output


def test_create_campaign_bounding_box_inverted_coords_exits_1():
    """sw_lat >= ne_lat must be a hard error, not a warning."""
    result = _run(
        "create-campaign", "Test",
        "--geo-method", "bounding_box",
        "--sw-lat", "51.6",   # south > north — inverted
        "--sw-lng", "-0.3",
        "--ne-lat", "51.4",
        "--ne-lng", "0.1",
    )
    assert result.exit_code == 1
    assert "Error" in result.output


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


# ---------------------------------------------------------------------------
# scrape — UUID validation
# ---------------------------------------------------------------------------


def test_scrape_invalid_uuid_exits_1():
    result = _run("scrape", "--campaign-id", "not-a-uuid")
    assert result.exit_code == 1
    assert "valid UUID" in result.output or "not a valid" in result.output.lower()


# ---------------------------------------------------------------------------
# scrape — campaign not found
# ---------------------------------------------------------------------------


@patch("src.cli.run_scrape_for_campaign")
def test_scrape_campaign_not_found_exits_1(mock_runner):
    mock_runner.side_effect = ValueError("Campaign not found")
    result = _run("scrape", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# scrape — summary output
# ---------------------------------------------------------------------------


@patch("src.cli.run_scrape_for_campaign")
def test_scrape_prints_summary_table(mock_runner):
    from src.scraper.runner import ScrapeSummary

    mock_runner.return_value = ScrapeSummary(
        hits_scraped=10,
        hits_skipped=2,
        hits_failed=1,
        pages_saved=35,
        pages_deduplicated=3,
        errors=0,
    )

    result = _run("scrape", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 0
    assert "Scrape complete" in result.output
    assert "10" in result.output   # hits_scraped
    assert "35" in result.output   # pages_saved


@patch("src.cli.run_scrape_for_campaign")
def test_scrape_with_errors_exits_1(mock_runner):
    from src.scraper.runner import ScrapeSummary

    mock_runner.return_value = ScrapeSummary(
        hits_scraped=5,
        hits_skipped=0,
        hits_failed=2,
        pages_saved=15,
        pages_deduplicated=0,
        errors=2,
        error_details=["hit=abc: timeout", "hit=def: HTTP 500"],
    )

    result = _run("scrape", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 1
    assert "timeout" in result.output or "Errors" in result.output


@patch("src.cli.run_scrape_for_campaign")
def test_scrape_no_errors_exits_0(mock_runner):
    from src.scraper.runner import ScrapeSummary

    mock_runner.return_value = ScrapeSummary(
        hits_scraped=3,
        hits_skipped=0,
        hits_failed=0,
        pages_saved=9,
        pages_deduplicated=0,
        errors=0,
    )

    result = _run("scrape", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# extract — UUID validation
# ---------------------------------------------------------------------------


def test_extract_invalid_uuid_exits_1():
    result = _run("extract", "--campaign-id", "not-a-uuid")
    assert result.exit_code == 1
    assert "valid UUID" in result.output or "not a valid" in result.output.lower()


# ---------------------------------------------------------------------------
# extract — campaign not found
# ---------------------------------------------------------------------------


@patch("src.cli.run_extraction_for_campaign")
def test_extract_campaign_not_found_exits_1(mock_runner):
    mock_runner.side_effect = ValueError("Campaign not found")
    result = _run("extract", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# extract — summary output
# ---------------------------------------------------------------------------


@patch("src.cli.run_extraction_for_campaign")
def test_extract_prints_summary_table(mock_runner):
    from src.extraction.runner import ExtractionSummary

    mock_runner.return_value = ExtractionSummary(
        hits_processed=10,
        hits_with_data=7,
        hits_zero_data=2,
        hits_failed=1,
        hits_skipped=0,
        contacts_created=15,
        emails_created=20,
        phones_created=8,
        errors=0,
    )

    result = _run("extract", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 0
    assert "Extraction complete" in result.output
    assert "10" in result.output   # hits_processed
    assert "15" in result.output   # contacts_created
    assert "20" in result.output   # emails_created


@patch("src.cli.run_extraction_for_campaign")
def test_extract_with_errors_exits_1(mock_runner):
    from src.extraction.runner import ExtractionSummary

    mock_runner.return_value = ExtractionSummary(
        hits_processed=5,
        hits_with_data=3,
        hits_zero_data=1,
        hits_failed=1,
        hits_skipped=0,
        contacts_created=5,
        emails_created=5,
        phones_created=2,
        errors=1,
        error_details=["hit=abc: db error"],
    )

    result = _run("extract", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 1
    assert "Errors" in result.output or "db error" in result.output


@patch("src.cli.run_extraction_for_campaign")
def test_extract_no_errors_exits_0(mock_runner):
    from src.extraction.runner import ExtractionSummary

    mock_runner.return_value = ExtractionSummary(
        hits_processed=5,
        hits_with_data=5,
        hits_zero_data=0,
        hits_failed=0,
        hits_skipped=0,
        contacts_created=8,
        emails_created=10,
        phones_created=4,
        errors=0,
    )

    result = _run("extract", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# verify — UUID validation
# ---------------------------------------------------------------------------


def test_verify_invalid_uuid_exits_1():
    result = _run("verify", "--campaign-id", "not-a-uuid")
    assert result.exit_code == 1
    assert "valid UUID" in result.output or "not a valid" in result.output.lower()


# ---------------------------------------------------------------------------
# verify — campaign not found
# ---------------------------------------------------------------------------


@patch("src.cli.run_verification_for_campaign")
def test_verify_campaign_not_found_exits_1(mock_runner):
    mock_runner.side_effect = ValueError("Campaign not found")
    result = _run("verify", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# verify — summary output
# ---------------------------------------------------------------------------


@patch("src.cli.run_verification_for_campaign")
def test_verify_prints_summary_table(mock_runner, tmp_path, monkeypatch):
    from src.verification.runner import VerificationSummary

    monkeypatch.chdir(tmp_path)

    mock_runner.return_value = (
        VerificationSummary(
            emails_verified=10,
            emails_valid=8,
            emails_invalid=1,
            emails_risky=1,
            phones_classified=5,
            websites_checked=3,
            websites_reachable=2,
            errors=0,
        ),
        {},
    )

    result = _run("verify", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 0
    assert "Verification complete" in result.output
    assert "10" in result.output   # emails_verified
    assert "8" in result.output    # emails_valid


@patch("src.cli.run_verification_for_campaign")
def test_verify_with_errors_exits_1(mock_runner, tmp_path, monkeypatch):
    from src.verification.runner import VerificationSummary

    monkeypatch.chdir(tmp_path)

    mock_runner.return_value = (
        VerificationSummary(
            emails_verified=2,
            emails_valid=1,
            emails_invalid=1,
            emails_risky=0,
            phones_classified=0,
            websites_checked=1,
            websites_reachable=0,
            errors=1,
            error_details=["DNS timeout for bad.com"],
        ),
        {},
    )

    result = _run("verify", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# score — UUID validation
# ---------------------------------------------------------------------------


def test_score_invalid_uuid_exits_1():
    result = _run("score", "--campaign-id", "not-a-uuid")
    assert result.exit_code == 1
    assert "valid UUID" in result.output or "not a valid" in result.output.lower()


# ---------------------------------------------------------------------------
# score — campaign not found
# ---------------------------------------------------------------------------


@patch("src.cli.run_scoring_for_campaign")
def test_score_campaign_not_found_exits_1(mock_runner):
    mock_runner.side_effect = ValueError("Campaign not found")
    result = _run("score", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# score — summary output
# ---------------------------------------------------------------------------


@patch("src.cli.run_scoring_for_campaign")
def test_score_prints_summary_table(mock_runner):
    from src.scoring.runner import ScoringRunSummary

    mock_runner.return_value = ScoringRunSummary(
        companies_processed=10,
        leads_created=8,
        leads_updated=2,
        leads_disqualified=1,
        hot=3,
        warm=4,
        cold=2,
        errors=0,
    )

    result = _run("score", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 0
    assert "Scoring complete" in result.output
    assert "10" in result.output   # companies_processed
    assert "8" in result.output    # leads_created


@patch("src.cli.run_scoring_for_campaign")
def test_score_with_errors_exits_1(mock_runner):
    from src.scoring.runner import ScoringRunSummary

    mock_runner.return_value = ScoringRunSummary(
        companies_processed=5,
        leads_created=3,
        leads_updated=1,
        leads_disqualified=0,
        hot=1,
        warm=2,
        cold=0,
        errors=1,
        error_details=["company=abc: db error"],
    )

    result = _run("score", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# review — UUID validation
# ---------------------------------------------------------------------------


def test_review_invalid_uuid_exits_1():
    result = _run("review", "--campaign-id", "not-a-uuid")
    assert result.exit_code == 1
    assert "valid UUID" in result.output or "not a valid" in result.output.lower()


# ---------------------------------------------------------------------------
# review — campaign not found
# ---------------------------------------------------------------------------


@patch("src.cli._run_review_for_campaign")
def test_review_campaign_not_found_exits_1(mock_runner):
    mock_runner.side_effect = ValueError("Campaign not found")
    result = _run("review", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# review — summary output
# ---------------------------------------------------------------------------


@patch("src.cli._run_review_for_campaign")
def test_review_prints_summary(mock_runner):
    mock_runner.return_value = {
        "reviewed": 5,
        "approved": 3,
        "rejected": 1,
        "needs_edit": 1,
        "skipped": 0,
    }

    result = _run("review", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 0
    assert "Review complete" in result.output
    assert "3" in result.output   # approved
    assert "Approved" in result.output


# ---------------------------------------------------------------------------
# export — UUID validation
# ---------------------------------------------------------------------------


def test_export_invalid_uuid_exits_1():
    result = _run("export", "--campaign-id", "not-a-uuid")
    assert result.exit_code == 1
    assert "valid UUID" in result.output or "not a valid" in result.output.lower()


# ---------------------------------------------------------------------------
# export — campaign not found
# ---------------------------------------------------------------------------


@patch("src.cli.run_export_for_campaign")
def test_export_campaign_not_found_exits_1(mock_runner):
    mock_runner.side_effect = ValueError("Campaign not found")
    result = _run("export", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# export — summary output
# ---------------------------------------------------------------------------


@patch("src.cli.run_export_for_campaign")
def test_export_prints_summary(mock_runner):
    from src.export.runner import ExportSummary

    mock_runner.return_value = ExportSummary(
        contacts_file="/tmp/contacts.csv",
        companies_file="/tmp/companies.csv",
        leads_file="/tmp/leads.csv",
        contacts_rows=10,
        companies_rows=3,
        leads_rows=13,
        approved_companies=13,
        errors=0,
    )

    result = _run("export", "--campaign-id", str(uuid.uuid4()))

    assert result.exit_code == 0
    assert "Export complete" in result.output
    assert "10" in result.output
    assert "3" in result.output


@patch("src.cli.run_export_for_campaign")
def test_export_with_errors_exits_1(mock_runner):
    from src.export.runner import ExportSummary

    mock_runner.return_value = ExportSummary(
        contacts_file="",
        companies_file="",
        leads_file="",
        contacts_rows=0,
        companies_rows=0,
        leads_rows=0,
        approved_companies=0,
        errors=1,
        error_details=["Failed to write contacts CSV: disk full"],
    )

    result = _run("export", "--campaign-id", str(uuid.uuid4()))
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# run — UUID validation
# ---------------------------------------------------------------------------


def test_run_invalid_uuid_exits_1():
    result = _run("run", "--campaign-id", "not-a-uuid")
    assert result.exit_code == 1
    assert "valid UUID" in result.output or "not a valid" in result.output.lower()


def test_run_invalid_from_stage_exits_1():
    result = _run("run", "--campaign-id", str(uuid.uuid4()), "--from-stage", "invalid_stage")
    assert result.exit_code == 1
    assert "invalid" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# run — summary output
# ---------------------------------------------------------------------------


@patch("src.cli.run_pipeline")
def test_run_prints_summary(mock_runner):
    from src.pipeline.runner import PipelineSummary, StageSummary

    cid = str(uuid.uuid4())
    mock_runner.return_value = PipelineSummary(
        campaign_id=cid,
        stages_run=["scrape", "extract"],
        stage_summaries={
            "scrape": StageSummary(stage="scrape", processed=5, succeeded=5),
            "extract": StageSummary(stage="extract", processed=5, succeeded=4),
        },
        total_errors=0,
    )

    result = _run("run", "--campaign-id", cid, "--from-stage", "scrape", "--to-stage", "extract")

    assert result.exit_code == 0
    assert "scrape" in result.output.lower() or "Pipeline" in result.output


@patch("src.cli.run_pipeline")
def test_run_with_errors_exits_1(mock_runner):
    from src.pipeline.runner import PipelineSummary, StageSummary

    cid = str(uuid.uuid4())
    mock_runner.return_value = PipelineSummary(
        campaign_id=cid,
        stages_run=["scrape"],
        stage_summaries={
            "scrape": StageSummary(stage="scrape", errors=["DB error"]),
        },
        total_errors=1,
    )

    result = _run("run", "--campaign-id", cid, "--from-stage", "scrape", "--to-stage", "scrape")
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# mark-contacted
# ---------------------------------------------------------------------------


def test_mark_contacted_invalid_uuid_exits_1():
    result = _run("mark-contacted", "--lead-id", "not-a-uuid")
    assert result.exit_code == 1


@patch("src.cli.mark_contacted")
@patch("src.cli.get_session")
def test_mark_contacted_lead_not_found_exits_1(mock_get_session, mock_fn):
    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx
    mock_fn.side_effect = ValueError("Lead not found")

    result = _run("mark-contacted", "--lead-id", str(uuid.uuid4()))
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


@patch("src.cli.mark_contacted")
@patch("src.cli.get_session")
def test_mark_contacted_invalid_transition_exits_1(mock_get_session, mock_fn):
    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx
    mock_fn.side_effect = ValueError("Cannot transition from new to contacted")

    result = _run("mark-contacted", "--lead-id", str(uuid.uuid4()))
    assert result.exit_code == 1


@patch("src.cli.mark_contacted")
@patch("src.cli.get_session")
def test_mark_contacted_success_exits_0(mock_get_session, mock_fn):
    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx
    mock_fn.return_value = MagicMock()

    result = _run("mark-contacted", "--lead-id", str(uuid.uuid4()))
    assert result.exit_code == 0
    assert "CONTACTED" in result.output


# ---------------------------------------------------------------------------
# mark-converted
# ---------------------------------------------------------------------------


def test_mark_converted_invalid_uuid_exits_1():
    result = _run("mark-converted", "--lead-id", "not-a-uuid")
    assert result.exit_code == 1


@patch("src.cli.mark_converted")
@patch("src.cli.get_session")
def test_mark_converted_lead_not_found_exits_1(mock_get_session, mock_fn):
    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx
    mock_fn.side_effect = ValueError("Lead not found")

    result = _run("mark-converted", "--lead-id", str(uuid.uuid4()))
    assert result.exit_code == 1


@patch("src.cli.mark_converted")
@patch("src.cli.get_session")
def test_mark_converted_success_exits_0(mock_get_session, mock_fn):
    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx
    mock_fn.return_value = MagicMock()

    result = _run("mark-converted", "--lead-id", str(uuid.uuid4()))
    assert result.exit_code == 0
    assert "CONVERTED" in result.output


# ---------------------------------------------------------------------------
# mark-churned
# ---------------------------------------------------------------------------


def test_mark_churned_invalid_uuid_exits_1():
    result = _run("mark-churned", "--lead-id", "not-a-uuid")
    assert result.exit_code == 1


@patch("src.cli.mark_churned")
@patch("src.cli.get_session")
def test_mark_churned_lead_not_found_exits_1(mock_get_session, mock_fn):
    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx
    mock_fn.side_effect = ValueError("Lead not found")

    result = _run("mark-churned", "--lead-id", str(uuid.uuid4()))
    assert result.exit_code == 1


@patch("src.cli.mark_churned")
@patch("src.cli.get_session")
def test_mark_churned_success_exits_0(mock_get_session, mock_fn):
    ctx = MagicMock()
    session = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_session.return_value = ctx
    mock_fn.return_value = MagicMock()

    result = _run("mark-churned", "--lead-id", str(uuid.uuid4()))
    assert result.exit_code == 0
    assert "CHURNED" in result.output
