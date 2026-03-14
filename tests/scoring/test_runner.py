"""Tests for src/scoring/runner.py"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from src.models.enums import LeadStatus, ScoreBand
from src.scoring.runner import ScoringRunSummary, run_scoring_for_campaign


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _company(company_id=None, name="Acme Ltd", website="https://acme.com"):
    c = MagicMock()
    c.id = company_id or uuid.uuid4()
    c.name = name
    c.website = website
    c.domain = "acme.com"
    c.address = "1 High St"
    c.city = "London"
    c.country = "GB"
    c.emails = []
    c.phones = []
    c.pages = []
    return c


def _make_lead(is_new=True, score=60.0, band=ScoreBand.WARM,
               status=LeadStatus.NEW):
    lead = MagicMock()
    lead.score = score
    lead.score_band = band
    lead.status = status
    lead.id = uuid.uuid4()
    lead.review_status = MagicMock()
    lead.campaign_id = uuid.uuid4()
    return lead


@contextmanager
def _mock_get_session(session):
    yield session


# ---------------------------------------------------------------------------
# Test: processes all extracted hits
# ---------------------------------------------------------------------------


def test_processes_all_extracted_companies():
    campaign_id = uuid.uuid4()
    company_id_1 = uuid.uuid4()
    company_id_2 = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company_1 = _company(company_id_1)
    company_2 = _company(company_id_2)

    lead_1 = _make_lead()
    lead_2 = _make_lead()

    session = MagicMock()
    session.get.side_effect = lambda cls, id_: (
        campaign if id_ == campaign_id
        else company_1 if id_ == company_id_1
        else company_2 if id_ == company_id_2
        else None
    )

    exec_results_map = {
        "first": True,  # track call index
        "calls": 0,
    }

    def execute_side_effect(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "discovery_hits" in stmt_str.lower():
            result.scalars.return_value.all.return_value = [company_id_1, company_id_2]
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute.side_effect = execute_side_effect
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None

    with patch("src.scoring.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.scoring.runner.derive_company_lead", side_effect=[lead_1, lead_2]):
        summary = run_scoring_for_campaign(campaign_id)

    assert summary.companies_processed == 2


# ---------------------------------------------------------------------------
# Test: counts leads_created correctly
# ---------------------------------------------------------------------------


def test_counts_leads_created():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    company = _company(company_id)
    lead = _make_lead(band=ScoreBand.HOT, status=LeadStatus.NEW)

    session = MagicMock()
    session.get.side_effect = lambda cls, id_: campaign if id_ == campaign_id else company

    def execute_side_effect(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "discovery_hits" in stmt_str.lower():
            result.scalars.return_value.all.return_value = [company_id]
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute.side_effect = execute_side_effect
    # No existing lead → new
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None

    with patch("src.scoring.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.scoring.runner.derive_company_lead", return_value=lead):
        summary = run_scoring_for_campaign(campaign_id)

    assert summary.leads_created == 1
    assert summary.leads_updated == 0


# ---------------------------------------------------------------------------
# Test: counts hot/warm/cold correctly
# ---------------------------------------------------------------------------


def test_counts_bands_correctly():
    campaign_id = uuid.uuid4()
    company_id_1 = uuid.uuid4()
    company_id_2 = uuid.uuid4()
    company_id_3 = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    companies = {
        company_id_1: _company(company_id_1),
        company_id_2: _company(company_id_2),
        company_id_3: _company(company_id_3),
    }

    hot_lead = _make_lead(band=ScoreBand.HOT, status=LeadStatus.NEW, score=80)
    warm_lead = _make_lead(band=ScoreBand.WARM, status=LeadStatus.NEW, score=60)
    cold_lead = _make_lead(band=ScoreBand.COLD, status=LeadStatus.NEW, score=30)

    session = MagicMock()
    session.get.side_effect = lambda cls, id_: (
        campaign if id_ == campaign_id else companies.get(id_)
    )

    def execute_side_effect(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "discovery_hits" in stmt_str.lower():
            result.scalars.return_value.all.return_value = [
                company_id_1, company_id_2, company_id_3
            ]
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute.side_effect = execute_side_effect
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None

    with patch("src.scoring.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.scoring.runner.derive_company_lead",
               side_effect=[hot_lead, warm_lead, cold_lead]):
        summary = run_scoring_for_campaign(campaign_id)

    assert summary.hot == 1
    assert summary.warm == 1
    assert summary.cold == 1


# ---------------------------------------------------------------------------
# Test: per-company exception doesn't stop processing
# ---------------------------------------------------------------------------


def test_per_company_error_does_not_stop_processing():
    campaign_id = uuid.uuid4()
    company_id_1 = uuid.uuid4()
    company_id_2 = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company_ok = _company(company_id_2)
    lead_ok = _make_lead(band=ScoreBand.WARM, status=LeadStatus.NEW)

    session = MagicMock()
    session.get.side_effect = lambda cls, id_: (
        campaign if id_ == campaign_id
        else None if id_ == company_id_1  # missing company
        else company_ok
    )

    def execute_side_effect(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "discovery_hits" in stmt_str.lower():
            result.scalars.return_value.all.return_value = [company_id_1, company_id_2]
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute.side_effect = execute_side_effect
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None

    with patch("src.scoring.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.scoring.runner.derive_company_lead", return_value=lead_ok):
        summary = run_scoring_for_campaign(campaign_id)

    # company_id_1 has no company → error recorded
    assert summary.errors >= 1
    # company_id_2 should still be processed
    assert summary.companies_processed >= 1


# ---------------------------------------------------------------------------
# Test: campaign not found raises ValueError
# ---------------------------------------------------------------------------


def test_campaign_not_found_raises():
    session = MagicMock()
    session.get.return_value = None  # campaign not found

    with patch("src.scoring.runner.get_session", return_value=_mock_get_session(session)):
        with pytest.raises(ValueError, match="not found"):
            run_scoring_for_campaign(uuid.uuid4())


# ---------------------------------------------------------------------------
# Test: website_results dict is respected
# ---------------------------------------------------------------------------


def test_website_results_passed_to_deriver():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    company = _company(company_id)
    lead = _make_lead(band=ScoreBand.HOT, status=LeadStatus.NEW)

    session = MagicMock()
    session.get.side_effect = lambda cls, id_: campaign if id_ == campaign_id else company

    def execute_side_effect(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "discovery_hits" in stmt_str.lower():
            result.scalars.return_value.all.return_value = [company_id]
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute.side_effect = execute_side_effect
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None

    website_results = {company_id: True}
    captured_calls = []

    def mock_derive(session, company, contacts, emails, phones, pages,
                    campaign_id, website_reachable):
        captured_calls.append(website_reachable)
        return lead

    with patch("src.scoring.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.scoring.runner.derive_company_lead", side_effect=mock_derive):
        run_scoring_for_campaign(campaign_id, website_results=website_results)

    assert captured_calls == [True]
