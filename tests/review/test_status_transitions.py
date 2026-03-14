"""Tests for review runner status transitions (approve/reject/needs-edit)."""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models.enums import LeadStatus, ReviewStatus
from src.review.runner import run_review_for_campaign


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead(status=LeadStatus.NEW, review_status=ReviewStatus.PENDING, score=60.0):
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.status = status
    lead.review_status = review_status
    lead.score = score
    lead.score_band = MagicMock()
    lead.score_band.value = "warm"
    lead.score_details = {}
    lead.review_decided_at = None
    lead.company = MagicMock()
    lead.company.id = uuid.uuid4()
    lead.company.name = "Acme Ltd"
    lead.company.domain = "acme.com"
    lead.company.website = "https://acme.com"
    lead.company.city = "London"
    lead.company.country = "GB"
    return lead


def _make_session(campaign, leads, contacts=None, emails=None, phones=None):
    session = MagicMock()
    session.get.side_effect = lambda cls, id_: campaign if id_ == campaign.id else None

    def execute_side_effect(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "company_leads" in stmt_str.lower():
            result.scalars.return_value.all.return_value = leads
        elif "contact" in stmt_str.lower():
            result.scalars.return_value.all.return_value = contacts or []
        elif "email" in stmt_str.lower():
            result.scalars.return_value.all.return_value = emails or []
        elif "phone" in stmt_str.lower():
            result.scalars.return_value.all.return_value = phones or []
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute.side_effect = execute_side_effect
    return session


@contextmanager
def _mock_get_session(session):
    yield session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_approve_with_status_new_sets_qualified():
    campaign_id = uuid.uuid4()
    campaign = MagicMock()
    campaign.id = campaign_id

    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(campaign, [lead])

    with patch("src.review.runner.get_session", return_value=_mock_get_session(session)), \
         patch("builtins.input", return_value="a"):
        result = run_review_for_campaign(campaign_id)

    assert lead.status == LeadStatus.QUALIFIED
    assert lead.review_status == ReviewStatus.APPROVED
    assert result["approved"] == 1


def test_approve_with_status_contacted_preserves_contacted():
    campaign_id = uuid.uuid4()
    campaign = MagicMock()
    campaign.id = campaign_id

    lead = _make_lead(status=LeadStatus.CONTACTED)
    session = _make_session(campaign, [lead])

    with patch("src.review.runner.get_session", return_value=_mock_get_session(session)), \
         patch("builtins.input", return_value="a"):
        run_review_for_campaign(campaign_id)

    assert lead.status == LeadStatus.CONTACTED


def test_approve_with_status_converted_preserves_converted():
    campaign_id = uuid.uuid4()
    campaign = MagicMock()
    campaign.id = campaign_id

    lead = _make_lead(status=LeadStatus.CONVERTED)
    session = _make_session(campaign, [lead])

    with patch("src.review.runner.get_session", return_value=_mock_get_session(session)), \
         patch("builtins.input", return_value="a"):
        run_review_for_campaign(campaign_id)

    assert lead.status == LeadStatus.CONVERTED


def test_reject_sets_disqualified():
    campaign_id = uuid.uuid4()
    campaign = MagicMock()
    campaign.id = campaign_id

    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(campaign, [lead])

    with patch("src.review.runner.get_session", return_value=_mock_get_session(session)), \
         patch("builtins.input", return_value="r"):
        result = run_review_for_campaign(campaign_id)

    assert lead.status == LeadStatus.DISQUALIFIED
    assert lead.review_status == ReviewStatus.REJECTED
    assert result["rejected"] == 1


def test_approve_with_status_disqualified_does_not_change_status(caplog):
    campaign_id = uuid.uuid4()
    campaign = MagicMock()
    campaign.id = campaign_id

    lead = _make_lead(status=LeadStatus.DISQUALIFIED)
    session = _make_session(campaign, [lead])

    with patch("src.review.runner.get_session", return_value=_mock_get_session(session)), \
         patch("builtins.input", return_value="a"), \
         caplog.at_level(logging.WARNING, logger="src.review.runner"):
        run_review_for_campaign(campaign_id)

    # Status must remain DISQUALIFIED
    assert lead.status == LeadStatus.DISQUALIFIED
    # Warning must be logged
    assert any("DISQUALIFIED" in r.message for r in caplog.records)


def test_needs_edit_sets_needs_edit_no_status_change():
    campaign_id = uuid.uuid4()
    campaign = MagicMock()
    campaign.id = campaign_id

    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(campaign, [lead])

    with patch("src.review.runner.get_session", return_value=_mock_get_session(session)), \
         patch("builtins.input", return_value="e"):
        result = run_review_for_campaign(campaign_id)

    assert lead.review_status == ReviewStatus.NEEDS_EDIT
    # Status unchanged from NEW
    assert lead.status == LeadStatus.NEW
    assert result["needs_edit"] == 1
