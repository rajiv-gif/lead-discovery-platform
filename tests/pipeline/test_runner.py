"""Tests for src/pipeline/runner.py"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.runner import STAGES, PipelineSummary, StageSummary, run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scrape_summary(scraped=5, failed=0, skipped=0, errors=0, error_details=None):
    s = MagicMock()
    s.hits_scraped = scraped
    s.hits_failed = failed
    s.hits_skipped = skipped
    s.errors = errors
    s.error_details = error_details or []
    return s


def _extract_summary(processed=5, with_data=4, failed=0, skipped=0, errors=0, error_details=None):
    s = MagicMock()
    s.hits_processed = processed
    s.hits_with_data = with_data
    s.hits_failed = failed
    s.hits_skipped = skipped
    s.errors = errors
    s.error_details = error_details or []
    return s


def _verify_summary(emails_verified=3, emails_valid=2, phones_classified=1,
                    errors=0, error_details=None):
    s = MagicMock()
    s.emails_verified = emails_verified
    s.emails_valid = emails_valid
    s.emails_invalid = 0
    s.emails_risky = 0
    s.phones_classified = phones_classified
    s.websites_checked = 1
    s.websites_reachable = 1
    s.errors = errors
    s.error_details = error_details or []
    return s


def _score_summary(companies_processed=5, leads_created=4, leads_updated=1,
                   errors=0, error_details=None):
    s = MagicMock()
    s.companies_processed = companies_processed
    s.leads_created = leads_created
    s.leads_updated = leads_updated
    s.leads_disqualified = 0
    s.hot = 1
    s.warm = 2
    s.cold = 1
    s.errors = errors
    s.error_details = error_details or []
    return s


def _discovery_summary(total=10, created=8, matched=2, errors=0, error_details=None):
    s = MagicMock()
    s.queries_run = 1
    s.total_results = total
    s.companies_created = created
    s.companies_matched = matched
    s.hits_created = total
    s.hits_skipped = 0
    s.errors = errors
    s.error_details = error_details or []
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_from_stage_scrape_skips_discover():
    campaign_id = uuid.uuid4()

    with patch("src.pipeline.runner.run_scrape_for_campaign",
               return_value=_scrape_summary()) as mock_scrape, \
         patch("src.pipeline.runner.run_extraction_for_campaign",
               return_value=_extract_summary()) as mock_extract, \
         patch("src.pipeline.runner.run_verification_for_campaign",
               return_value=(_verify_summary(), {})) as mock_verify, \
         patch("src.pipeline.runner.run_scoring_for_campaign",
               return_value=_score_summary()) as mock_score:
        summary = run_pipeline(campaign_id, from_stage="scrape", to_stage="score")

    assert "discover" not in summary.stages_run
    assert "scrape" in summary.stages_run


def test_to_stage_verify_stops_before_score():
    campaign_id = uuid.uuid4()

    with patch("src.pipeline.runner.run_scrape_for_campaign",
               return_value=_scrape_summary()), \
         patch("src.pipeline.runner.run_extraction_for_campaign",
               return_value=_extract_summary()), \
         patch("src.pipeline.runner.run_verification_for_campaign",
               return_value=(_verify_summary(), {})):
        summary = run_pipeline(campaign_id, from_stage="scrape", to_stage="verify")

    assert "score" not in summary.stages_run
    assert "verify" in summary.stages_run


def test_dry_run_calls_no_runners():
    campaign_id = uuid.uuid4()

    with patch("src.pipeline.runner.run_scrape_for_campaign") as mock_scrape, \
         patch("src.pipeline.runner.run_extraction_for_campaign") as mock_extract, \
         patch("src.pipeline.runner.run_verification_for_campaign") as mock_verify, \
         patch("src.pipeline.runner.run_scoring_for_campaign") as mock_score:
        summary = run_pipeline(
            campaign_id,
            from_stage="scrape",
            to_stage="score",
            dry_run=True,
        )

    mock_scrape.assert_not_called()
    mock_extract.assert_not_called()
    mock_verify.assert_not_called()
    mock_score.assert_not_called()

    for ss in summary.stage_summaries.values():
        assert ss.skipped >= 1


def test_website_results_passed_in_process_when_verify_and_score_run():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()
    website_results = {company_id: True}

    verify_sum = _verify_summary()

    captured_website_results = []

    def mock_score(cid, website_results=None):
        captured_website_results.append(website_results)
        return _score_summary()

    with patch("src.pipeline.runner.run_scrape_for_campaign",
               return_value=_scrape_summary()), \
         patch("src.pipeline.runner.run_extraction_for_campaign",
               return_value=_extract_summary()), \
         patch("src.pipeline.runner.run_verification_for_campaign",
               return_value=(verify_sum, website_results)), \
         patch("src.pipeline.runner.run_scoring_for_campaign",
               side_effect=mock_score):
        run_pipeline(campaign_id, from_stage="scrape", to_stage="score")

    assert len(captured_website_results) == 1
    assert captured_website_results[0] == website_results


def test_invalid_from_stage_raises_value_error():
    with pytest.raises(ValueError, match="Invalid from_stage"):
        run_pipeline(uuid.uuid4(), from_stage="invalid_stage")


def test_from_stage_after_to_stage_raises_value_error():
    with pytest.raises(ValueError, match="must come before"):
        run_pipeline(uuid.uuid4(), from_stage="score", to_stage="scrape")


def test_stage_error_does_not_crash_pipeline():
    """An exception in one stage should not prevent subsequent stages from running."""
    campaign_id = uuid.uuid4()

    def bad_scrape(cid):
        raise RuntimeError("Scrape exploded!")

    with patch("src.pipeline.runner.run_scrape_for_campaign",
               side_effect=bad_scrape), \
         patch("src.pipeline.runner.run_extraction_for_campaign",
               return_value=_extract_summary()) as mock_extract, \
         patch("src.pipeline.runner.run_verification_for_campaign",
               return_value=(_verify_summary(), {})) as mock_verify, \
         patch("src.pipeline.runner.run_scoring_for_campaign",
               return_value=_score_summary()) as mock_score:
        summary = run_pipeline(campaign_id, from_stage="scrape", to_stage="score")

    # Scrape failed but subsequent stages ran
    assert mock_extract.called
    assert mock_verify.called
    assert mock_score.called

    # Scrape stage has an error recorded
    scrape_ss = summary.stage_summaries.get("scrape")
    assert scrape_ss is not None
    assert len(scrape_ss.errors) >= 1


def test_total_errors_sums_across_all_stages():
    campaign_id = uuid.uuid4()

    scrape_sum = _scrape_summary(errors=1, error_details=["scrape error"])
    extract_sum = _extract_summary(errors=2, error_details=["e1", "e2"])
    verify_sum = _verify_summary()
    score_sum = _score_summary()

    with patch("src.pipeline.runner.run_scrape_for_campaign",
               return_value=scrape_sum), \
         patch("src.pipeline.runner.run_extraction_for_campaign",
               return_value=extract_sum), \
         patch("src.pipeline.runner.run_verification_for_campaign",
               return_value=(verify_sum, {})), \
         patch("src.pipeline.runner.run_scoring_for_campaign",
               return_value=score_sum):
        summary = run_pipeline(campaign_id, from_stage="scrape", to_stage="score")

    # scrape had 1 error detail, extract had 2
    assert summary.total_errors == 3
