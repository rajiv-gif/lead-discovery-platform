"""Tests for src/verification/runner.py

Uses mock DB session and in-memory objects to test runner behaviour without
a live PostgreSQL instance.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from src.models.enums import EmailStatus, PhoneType
from src.verification.runner import VerificationSummary, run_verification_for_campaign


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_company(company_id=None, website=None, country=None, domain=None):
    c = MagicMock()
    c.id = company_id or uuid.uuid4()
    c.website = website
    c.country = country
    c.domain = domain
    c.emails = []
    c.phones = []
    return c


def _make_email(company_id, address="test@example.com", status=EmailStatus.UNVERIFIED,
                contact_id=None, mx_valid=None):
    e = MagicMock()
    e.id = uuid.uuid4()
    e.company_id = company_id
    e.address = address
    e.status = status
    e.contact_id = contact_id
    e.mx_valid = mx_valid
    e.verified_at = None
    return e


def _make_phone(company_id, number="+442079460958", raw_number=None,
                phone_type=PhoneType.UNKNOWN, contact_id=None):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.company_id = company_id
    p.number = number
    p.raw_number = raw_number
    p.phone_type = phone_type
    p.contact_id = contact_id
    return p


def _make_hit(campaign_id, company_id, status="extracted"):
    h = MagicMock()
    h.id = uuid.uuid4()
    h.campaign_id = campaign_id
    h.company_id = company_id
    h.status = status
    return h


def _make_session(campaign, hits, company, emails, phones):
    """Build a mock SQLAlchemy session that returns the given objects."""
    session = MagicMock()
    session.get.side_effect = lambda cls, id_: company if id_ == company.id else campaign if id_ == campaign.id else None

    # session.execute() is used for queries; return appropriate scalars
    exec_results = MagicMock()

    def execute_side_effect(stmt):
        result = MagicMock()
        # Determine what query is being executed by inspecting (simplified)
        stmt_str = str(stmt)
        if "discovery_hits" in stmt_str.lower():
            result.scalars.return_value.all.return_value = hits
        elif "emails" in stmt_str.lower():
            result.scalars.return_value.all.return_value = emails
        elif "phones" in stmt_str.lower():
            result.scalars.return_value.all.return_value = phones
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute.side_effect = execute_side_effect
    return session


@contextmanager
def _mock_get_session(session):
    yield session


# ---------------------------------------------------------------------------
# Test: updates email status on valid MX
# ---------------------------------------------------------------------------


def test_updates_email_status_on_valid_mx():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company = _make_company(company_id=company_id)
    email = _make_email(company_id, address="test@validmx.com", status=EmailStatus.UNVERIFIED)
    hit = _make_hit(campaign_id, company_id)

    session = _make_session(campaign, [hit], company, [email], [])

    with patch("src.verification.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.verification.runner.verify_email", return_value=(EmailStatus.VALID, True)):
        summary, website_results = run_verification_for_campaign(campaign_id)

    assert email.status == EmailStatus.VALID
    assert email.mx_valid is True
    assert summary.emails_verified == 1
    assert summary.emails_valid == 1


# ---------------------------------------------------------------------------
# Test: updates email status on invalid MX
# ---------------------------------------------------------------------------


def test_updates_email_status_on_invalid_mx():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company = _make_company(company_id=company_id)
    email = _make_email(company_id, status=EmailStatus.UNVERIFIED)
    hit = _make_hit(campaign_id, company_id)

    session = _make_session(campaign, [hit], company, [email], [])

    with patch("src.verification.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.verification.runner.verify_email", return_value=(EmailStatus.INVALID, False)):
        summary, _ = run_verification_for_campaign(campaign_id)

    assert email.status == EmailStatus.INVALID
    assert summary.emails_invalid == 1


# ---------------------------------------------------------------------------
# Test: updates phone_type for mobile
# ---------------------------------------------------------------------------


def test_updates_phone_type_for_mobile():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company = _make_company(company_id=company_id)
    phone = _make_phone(company_id, number="+447700900123", phone_type=PhoneType.UNKNOWN)
    hit = _make_hit(campaign_id, company_id)

    session = _make_session(campaign, [hit], company, [], [phone])

    with patch("src.verification.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.verification.runner.classify_phone", return_value=PhoneType.MOBILE):
        summary, _ = run_verification_for_campaign(campaign_id)

    assert phone.phone_type == PhoneType.MOBILE
    assert summary.phones_classified == 1


# ---------------------------------------------------------------------------
# Test: skips already-verified emails
# ---------------------------------------------------------------------------


def test_skips_already_verified_emails():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company = _make_company(company_id=company_id)
    email = _make_email(company_id, status=EmailStatus.VALID)  # already verified
    hit = _make_hit(campaign_id, company_id)

    # Only UNVERIFIED emails are returned by the query
    session = _make_session(campaign, [hit], company, [], [])  # empty email list

    with patch("src.verification.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.verification.runner.verify_email") as mock_verify:
        summary, _ = run_verification_for_campaign(campaign_id)

    mock_verify.assert_not_called()
    assert summary.emails_verified == 0


# ---------------------------------------------------------------------------
# Test: handles DNS error gracefully (email marked risky, no exception)
# ---------------------------------------------------------------------------


def test_handles_dns_error_gracefully():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company = _make_company(company_id=company_id)
    email = _make_email(company_id, status=EmailStatus.UNVERIFIED)
    hit = _make_hit(campaign_id, company_id)

    session = _make_session(campaign, [hit], company, [email], [])

    with patch("src.verification.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.verification.runner.verify_email", return_value=(EmailStatus.RISKY, False)):
        summary, _ = run_verification_for_campaign(campaign_id)

    assert email.status == EmailStatus.RISKY
    assert summary.emails_risky == 1
    assert summary.errors == 0  # RISKY is not an error


# ---------------------------------------------------------------------------
# Test: handles missing company gracefully
# ---------------------------------------------------------------------------


def test_handles_missing_company_gracefully():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    hit = _make_hit(campaign_id, company_id)

    session = MagicMock()
    # session.get returns campaign but not company
    session.get.side_effect = lambda cls, id_: campaign if id_ == campaign_id else None

    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [hit]
    session.execute.return_value = exec_result

    with patch("src.verification.runner.get_session", return_value=_mock_get_session(session)):
        summary, _ = run_verification_for_campaign(campaign_id)

    assert summary.errors == 1


# ---------------------------------------------------------------------------
# Test: returns correct VerificationSummary counts
# ---------------------------------------------------------------------------


def test_returns_correct_summary_counts():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company = _make_company(company_id=company_id, website="https://example.com")
    email1 = _make_email(company_id, address="a@example.com", status=EmailStatus.UNVERIFIED)
    email2 = _make_email(company_id, address="b@example.com", status=EmailStatus.UNVERIFIED)
    phone = _make_phone(company_id, phone_type=PhoneType.UNKNOWN)
    hit = _make_hit(campaign_id, company_id)

    session = _make_session(campaign, [hit], company, [email1, email2], [phone])

    with patch("src.verification.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.verification.runner.verify_email", return_value=(EmailStatus.VALID, True)), \
         patch("src.verification.runner.classify_phone", return_value=PhoneType.MOBILE), \
         patch("src.verification.runner.check_website", return_value=True):
        summary, website_results = run_verification_for_campaign(campaign_id)

    assert summary.emails_verified == 2
    assert summary.emails_valid == 2
    assert summary.phones_classified == 1
    assert summary.websites_checked == 1
    assert summary.websites_reachable == 1
    assert website_results[company_id] is True


# ---------------------------------------------------------------------------
# Test: website not checked when company.website is None
# ---------------------------------------------------------------------------


def test_no_website_check_when_website_is_none():
    campaign_id = uuid.uuid4()
    company_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id

    company = _make_company(company_id=company_id, website=None)
    hit = _make_hit(campaign_id, company_id)

    session = _make_session(campaign, [hit], company, [], [])

    with patch("src.verification.runner.get_session", return_value=_mock_get_session(session)), \
         patch("src.verification.runner.check_website") as mock_check:
        summary, website_results = run_verification_for_campaign(campaign_id)

    mock_check.assert_not_called()
    assert summary.websites_checked == 0
    assert company_id not in website_results
