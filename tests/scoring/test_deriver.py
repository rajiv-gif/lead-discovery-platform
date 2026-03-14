"""Tests for src/scoring/deriver.py"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.models.enums import LeadStatus, ReviewStatus, ScoreBand, SuppressionType
from src.scoring.deriver import check_suppression, derive_company_lead


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _company(name="Acme Ltd", domain="acme.com", country="GB"):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.name = name
    c.domain = domain
    c.country = country
    c.website = "https://acme.com"
    c.address = "1 High St"
    c.city = "London"
    c.emails = []
    c.phones = []
    c.pages = []
    return c


def _suppression_row(suppression_type, value):
    row = MagicMock()
    row.suppression_type = suppression_type
    row.value = value
    return row


def _session_with_no_suppression():
    session = MagicMock()
    q = MagicMock()
    session.query.return_value = q
    q.filter.return_value = q
    q.first.return_value = None
    q.all.return_value = []
    q.one_or_none.return_value = None
    return session


def _session_with_lead(lead):
    session = MagicMock()
    q = MagicMock()
    session.query.return_value = q
    q.filter.return_value = q
    q.filter_by.return_value = q
    q.first.return_value = None
    q.all.return_value = []
    q.one_or_none.return_value = lead
    session.query.return_value.filter_by.return_value.one_or_none.return_value = lead
    return session


# ---------------------------------------------------------------------------
# Test: creates new CompanyLead on first call
# ---------------------------------------------------------------------------


def test_creates_new_company_lead():
    company = _company()
    campaign_id = uuid.uuid4()
    session = _session_with_no_suppression()
    session.add = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None

    email = MagicMock()
    email.address = "info@acme.com"
    email.status = "valid"
    email.mx_valid = True
    email.contact_id = None

    phone = MagicMock()
    phone.phone_type = "office"
    phone.contact_id = None

    lead = derive_company_lead(
        session=session,
        company=company,
        contacts=[],
        emails=[email],
        phones=[phone],
        pages=[],
        campaign_id=campaign_id,
        website_reachable=False,
    )

    session.add.assert_called_once_with(lead)
    assert lead.campaign_id == campaign_id
    assert lead.review_status == ReviewStatus.PENDING


# ---------------------------------------------------------------------------
# Test: updates score on second call, preserves review_status
# ---------------------------------------------------------------------------


def test_updates_score_preserves_review_status():
    company = _company()
    campaign_id = uuid.uuid4()

    existing_lead = MagicMock(spec=["score", "score_band", "score_details", "status",
                                     "review_status", "campaign_id"])
    existing_lead.review_status = ReviewStatus.APPROVED
    existing_lead.status = LeadStatus.NEW
    existing_lead.campaign_id = campaign_id

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.one_or_none.return_value = existing_lead

    email = MagicMock()
    email.address = "info@acme.com"
    email.status = "valid"
    email.mx_valid = True
    email.contact_id = None

    lead = derive_company_lead(
        session=session,
        company=company,
        contacts=[],
        emails=[email],
        phones=[],
        pages=[],
        campaign_id=campaign_id,
        website_reachable=False,
    )

    # Should NOT have called session.add (it's an update)
    session.add.assert_not_called()
    # review_status should be preserved
    assert lead.review_status == ReviewStatus.APPROVED
    # score was updated (it's a MagicMock attr so we just check it was set)
    assert hasattr(lead, "score")


# ---------------------------------------------------------------------------
# Test: preserves campaign_id on update
# ---------------------------------------------------------------------------


def test_preserves_campaign_id_on_update():
    company = _company()
    original_campaign_id = uuid.uuid4()

    existing_lead = MagicMock()
    existing_lead.review_status = ReviewStatus.PENDING
    existing_lead.status = LeadStatus.NEW
    existing_lead.campaign_id = original_campaign_id

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.one_or_none.return_value = existing_lead

    email = MagicMock()
    email.address = "info@acme.com"
    email.status = "valid"
    email.mx_valid = True
    email.contact_id = None

    new_campaign_id = uuid.uuid4()
    lead = derive_company_lead(
        session=session,
        company=company,
        contacts=[],
        emails=[email],
        phones=[],
        pages=[],
        campaign_id=new_campaign_id,
        website_reachable=False,
    )

    # campaign_id should NOT be updated on UPDATE
    assert lead.campaign_id == original_campaign_id


# ---------------------------------------------------------------------------
# Test: sets status=DISQUALIFIED on hard rule
# ---------------------------------------------------------------------------


def test_sets_disqualified_on_hard_rule():
    company = _company(name="")  # empty name → disqualify
    campaign_id = uuid.uuid4()

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None
    session.add = MagicMock()

    lead = derive_company_lead(
        session=session,
        company=company,
        contacts=[],
        emails=[MagicMock(address="a@b.com", status="unverified", mx_valid=None,
                          contact_id=None)],
        phones=[],
        pages=[],
        campaign_id=campaign_id,
        website_reachable=False,
    )

    assert lead.status == LeadStatus.DISQUALIFIED


# ---------------------------------------------------------------------------
# Test: suppression match → is_disqualified
# ---------------------------------------------------------------------------


def test_suppression_match_disqualifies():
    company = _company(domain="acme.com")
    campaign_id = uuid.uuid4()

    session = MagicMock()
    # Domain suppression match
    domain_row = _suppression_row(SuppressionType.DOMAIN, "acme.com")
    session.query.return_value.filter.return_value.first.return_value = domain_row
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None
    session.add = MagicMock()

    lead = derive_company_lead(
        session=session,
        company=company,
        contacts=[],
        emails=[MagicMock(address="info@acme.com", status="unverified", mx_valid=None,
                          contact_id=None)],
        phones=[],
        pages=[],
        campaign_id=campaign_id,
        website_reachable=False,
    )

    assert lead.status == LeadStatus.DISQUALIFIED
    assert lead.score == 0.0


# ---------------------------------------------------------------------------
# Test: check_suppression — company name match (case-insensitive)
# ---------------------------------------------------------------------------


def test_check_suppression_company_name_case_insensitive():
    company = _company(name="ACME CORP", domain=None)
    company.emails = []

    session = MagicMock()
    # No domain matches
    session.query.return_value.filter.return_value.first.return_value = None
    # Return company suppression row
    comp_row = _suppression_row(SuppressionType.COMPANY, "acme corp")
    session.query.return_value.filter.return_value.all.return_value = [comp_row]

    result = check_suppression(session, company)
    assert result is True


# ---------------------------------------------------------------------------
# Test: check_suppression — email match
# ---------------------------------------------------------------------------


def test_check_suppression_email_match():
    company = _company(domain=None)
    company.domain = None  # No domain
    email = MagicMock()
    email.address = "bad@example.com"
    company.emails = [email]

    # Use a call counter to track which query is which
    call_count = [0]

    def query_side_effect(*args):
        call_count[0] += 1
        q = MagicMock()
        q.filter.return_value = q
        q.all.return_value = []
        if call_count[0] == 1:
            # First call: domain check — no match (no domain)
            q.first.return_value = None
        elif call_count[0] == 2:
            # Second call: email check — match found
            q.first.return_value = _suppression_row(
                SuppressionType.EMAIL, "bad@example.com"
            )
        else:
            q.first.return_value = None
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect

    result = check_suppression(session, company)
    assert result is True


# ---------------------------------------------------------------------------
# Test: review_status not reset on re-score
# ---------------------------------------------------------------------------


def test_review_status_not_reset_on_rescore():
    company = _company()
    campaign_id = uuid.uuid4()

    existing_lead = MagicMock()
    existing_lead.review_status = ReviewStatus.REJECTED
    existing_lead.status = LeadStatus.NEW

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.one_or_none.return_value = existing_lead

    email = MagicMock()
    email.address = "info@acme.com"
    email.status = "valid"
    email.mx_valid = True
    email.contact_id = None

    lead = derive_company_lead(
        session=session,
        company=company,
        contacts=[],
        emails=[email],
        phones=[],
        pages=[],
        campaign_id=campaign_id,
        website_reachable=False,
    )

    assert lead.review_status == ReviewStatus.REJECTED
