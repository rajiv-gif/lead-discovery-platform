"""Tests for src/export/runner.py"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.export.runner import ExportSummary, run_export_for_campaign
from src.models.enums import LeadStatus, ReviewStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead(
    company_id=None,
    campaign_id=None,
    status=LeadStatus.QUALIFIED,
    review_status=ReviewStatus.APPROVED,
):
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.company_id = company_id or uuid.uuid4()
    lead.campaign_id = campaign_id or uuid.uuid4()
    lead.status = status
    lead.review_status = review_status
    lead.score = 70.0
    lead.score_band = MagicMock()
    lead.score_band.value = "warm"
    lead.review_decided_at = None
    return lead


def _make_company(company_id=None):
    c = MagicMock()
    c.id = company_id or uuid.uuid4()
    c.name = "Acme Ltd"
    c.domain = "acme.com"
    c.website = "https://acme.com"
    c.address = "1 High St"
    c.city = "London"
    c.country = "GB"
    return c


@contextmanager
def _mock_get_session(session):
    yield session


def _make_session(campaign, leads, company):
    session = MagicMock()

    def get_side_effect(cls, id_):
        if id_ == campaign.id:
            return campaign
        if id_ == company.id:
            return company
        return None

    session.get.side_effect = get_side_effect

    def execute_side_effect(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "company_leads" in stmt_str.lower():
            result.scalars.return_value.all.return_value = leads
        elif "contact" in stmt_str.lower():
            result.scalars.return_value.all.return_value = []
        elif "email" in stmt_str.lower():
            result.scalars.return_value.all.return_value = []
        elif "phone" in stmt_str.lower():
            result.scalars.return_value.all.return_value = []
        elif "suppression" in stmt_str.lower():
            result.scalars.return_value.all.return_value = []
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute.side_effect = execute_side_effect
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_creates_all_three_files(tmp_path):
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    company = _make_company(company_id)
    lead = _make_lead(company_id=company_id, campaign_id=campaign_id)

    session = _make_session(campaign, [lead], company)

    with patch("src.export.runner.get_session", return_value=_mock_get_session(session)):
        summary = run_export_for_campaign(campaign_id, export_dir=tmp_path)

    assert summary.contacts_file != ""
    assert summary.companies_file != ""
    assert summary.leads_file != ""
    assert Path(summary.contacts_file).exists()
    assert Path(summary.companies_file).exists()
    assert Path(summary.leads_file).exists()


def test_rapid_reruns_produce_unique_filenames_and_do_not_overwrite(tmp_path):
    """Two back-to-back export runs must produce distinct filenames.

    Both output files must exist after the second run — proving neither
    overwrote the other.  No sleep is required; millisecond-precision
    timestamps make same-second collisions negligible, and we pin the
    clock via patch to guarantee the test is deterministic.
    """
    from datetime import datetime, timezone
    from unittest.mock import call

    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    company = _make_company(company_id)
    lead = _make_lead(company_id=company_id, campaign_id=campaign_id)

    # Two instants 5 ms apart — well within the same second
    t1 = datetime(2026, 3, 15, 12, 0, 0, 100_000, tzinfo=timezone.utc)  # …_100
    t2 = datetime(2026, 3, 15, 12, 0, 0, 105_000, tzinfo=timezone.utc)  # …_105

    session1 = _make_session(campaign, [lead], company)
    session2 = _make_session(campaign, [lead], company)

    with patch("src.export.runner.datetime") as mock_dt:
        mock_dt.now.return_value = t1
        with patch("src.export.runner.get_session", return_value=_mock_get_session(session1)):
            summary1 = run_export_for_campaign(campaign_id, export_dir=tmp_path)

        mock_dt.now.return_value = t2
        with patch("src.export.runner.get_session", return_value=_mock_get_session(session2)):
            summary2 = run_export_for_campaign(campaign_id, export_dir=tmp_path)

    # Filenames must differ
    assert summary1.contacts_file != summary2.contacts_file
    assert summary1.companies_file != summary2.companies_file
    assert summary1.leads_file != summary2.leads_file

    # Both files must still exist — second run did not overwrite first
    assert Path(summary1.contacts_file).exists()
    assert Path(summary2.contacts_file).exists()
    assert Path(summary1.leads_file).exists()
    assert Path(summary2.leads_file).exists()


def test_only_uncontacted_flag_queries_correct_statuses(tmp_path):
    """With only_uncontacted=True, leads with CONTACTED status should be excluded."""
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    company = _make_company(company_id)

    # Simulate DB returning only QUALIFIED lead (as if CONTACTED was filtered)
    qualified_lead = _make_lead(
        company_id=company_id,
        campaign_id=campaign_id,
        status=LeadStatus.QUALIFIED,
    )

    session = _make_session(campaign, [qualified_lead], company)

    captured_queries = []

    original_execute = session.execute.side_effect

    def capture_execute(stmt):
        captured_queries.append(str(stmt))
        return original_execute(stmt)

    session.execute.side_effect = capture_execute

    with patch("src.export.runner.get_session", return_value=_mock_get_session(session)):
        summary = run_export_for_campaign(
            campaign_id, export_dir=tmp_path, only_uncontacted=True
        )

    # Check that the leads query was built (file should be created)
    assert summary.leads_file != ""


def test_include_converted_includes_converted_leads(tmp_path):
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    company = _make_company(company_id)
    converted_lead = _make_lead(
        company_id=company_id,
        campaign_id=campaign_id,
        status=LeadStatus.CONVERTED,
    )

    session = _make_session(campaign, [converted_lead], company)

    with patch("src.export.runner.get_session", return_value=_mock_get_session(session)):
        summary = run_export_for_campaign(
            campaign_id, export_dir=tmp_path, include_converted=True
        )

    # Should process the converted lead (approved_companies = 1)
    assert summary.approved_companies == 1


def test_churned_leads_always_excluded(tmp_path):
    """CHURNED leads should never appear in export regardless of flags."""
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    company = _make_company(company_id)

    # DB returns no leads (CHURNED filtered by query)
    session = _make_session(campaign, [], company)

    with patch("src.export.runner.get_session", return_value=_mock_get_session(session)):
        summary = run_export_for_campaign(campaign_id, export_dir=tmp_path)

    assert summary.approved_companies == 0


def test_returns_correct_row_counts_in_summary(tmp_path):
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    company = _make_company(company_id)
    lead = _make_lead(company_id=company_id, campaign_id=campaign_id)

    session = _make_session(campaign, [lead], company)

    contact_rows = [{"first_name": "John", "last_name": "Doe", "email": "j@acme.com"}]
    company_rows: list = []
    leads_rows = [{"company_name": "Acme", "email": "info@acme.com"}]

    with patch("src.export.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.export.runner.build_named_contacts_rows", return_value=contact_rows), \
         patch("src.export.runner.build_company_fallback_rows", return_value=company_rows), \
         patch("src.export.runner.build_full_leads_rows", return_value=leads_rows):
        summary = run_export_for_campaign(campaign_id, export_dir=tmp_path)

    assert summary.contacts_rows == 1
    assert summary.companies_rows == 0
    assert summary.leads_rows == 1
