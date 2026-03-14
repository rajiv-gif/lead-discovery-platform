"""Tests for src/scoring/scorer.py — pure function, no mocks."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from src.models.enums import EmailStatus, PageType, PhoneType, ScoreBand
from src.scoring.scorer import ScoringResult, compute_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _company(name="Acme Ltd", website="https://acme.com", address="1 High St",
             city="London", country="GB", domain="acme.com"):
    c = MagicMock()
    c.name = name
    c.website = website
    c.address = address
    c.city = city
    c.country = country
    c.domain = domain
    return c


def _contact(full_name="John Smith", title="CEO"):
    c = MagicMock()
    c.full_name = full_name
    c.title = title
    c.id = uuid.uuid4()
    return c


def _email(status=EmailStatus.VALID, mx_valid=True, contact_id=None):
    e = MagicMock()
    e.status = status
    e.mx_valid = mx_valid
    e.contact_id = contact_id
    return e


def _phone(phone_type=PhoneType.MOBILE, contact_id=None):
    p = MagicMock()
    p.phone_type = phone_type
    p.contact_id = contact_id
    return p


def _page(page_type=PageType.HOMEPAGE, word_count=100):
    pg = MagicMock()
    pg.page_type = page_type
    pg.word_count = word_count
    return pg


# ---------------------------------------------------------------------------
# Hard disqualification: missing name
# ---------------------------------------------------------------------------


def test_missing_name_is_disqualified():
    result = compute_score(
        company=_company(name=""),
        contacts=[_contact()],
        emails=[_email()],
        phones=[],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    assert result.is_disqualified is True
    assert result.score_band == ScoreBand.DISQUALIFIED
    assert result.score == 0.0


def test_none_name_is_disqualified():
    result = compute_score(
        company=_company(name=None),
        contacts=[],
        emails=[_email()],
        phones=[],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    assert result.is_disqualified is True
    assert result.score_band == ScoreBand.DISQUALIFIED


# ---------------------------------------------------------------------------
# Hard disqualification: no emails AND no phones
# ---------------------------------------------------------------------------


def test_no_emails_no_phones_is_disqualified():
    result = compute_score(
        company=_company(),
        contacts=[_contact()],
        emails=[],
        phones=[],
        pages=[_page()],
        website_reachable=True,
        is_suppressed=False,
    )
    assert result.is_disqualified is True
    assert result.score_band == ScoreBand.DISQUALIFIED


# ---------------------------------------------------------------------------
# Hard disqualification: suppressed
# ---------------------------------------------------------------------------


def test_suppressed_is_disqualified():
    result = compute_score(
        company=_company(),
        contacts=[_contact()],
        emails=[_email()],
        phones=[_phone()],
        pages=[_page()],
        website_reachable=True,
        is_suppressed=True,
    )
    assert result.is_disqualified is True
    assert result.score_band == ScoreBand.DISQUALIFIED


# ---------------------------------------------------------------------------
# Full data → high score in HOT band
# ---------------------------------------------------------------------------


def test_full_data_is_hot():
    contact = _contact()
    result = compute_score(
        company=_company(),
        contacts=[contact],
        emails=[
            _email(status=EmailStatus.VALID, mx_valid=True, contact_id=contact.id),
            _email(status=EmailStatus.VALID, mx_valid=True, contact_id=None),   # company-level
        ],
        phones=[
            _phone(phone_type=PhoneType.MOBILE, contact_id=contact.id),
            _phone(phone_type=PhoneType.OFFICE, contact_id=None),               # company-level
        ],
        pages=[
            _page(page_type=PageType.TEAM, word_count=200),
            _page(page_type=PageType.HOMEPAGE, word_count=500),
        ],
        website_reachable=True,
        is_suppressed=False,
    )
    assert result.is_disqualified is False
    assert result.score_band == ScoreBand.HOT
    assert result.score >= 75


# ---------------------------------------------------------------------------
# Zero contacts but emails → Dim A partial, Dim B positive
# ---------------------------------------------------------------------------


def test_no_contacts_emails_only():
    result = compute_score(
        company=_company(),
        contacts=[],
        emails=[_email(contact_id=None)],   # company-level
        phones=[],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    assert result.is_disqualified is False
    assert result.score_details["contact_richness"] == 0
    assert result.score_details["channel_availability"] >= 10  # company email


# ---------------------------------------------------------------------------
# score_details contains all 5 dimensions
# ---------------------------------------------------------------------------


def test_score_details_contains_all_dimensions():
    result = compute_score(
        company=_company(),
        contacts=[],
        emails=[_email(contact_id=None)],
        phones=[],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    for key in ("contact_richness", "channel_availability", "verification_quality",
                "scrape_quality", "location", "website_reachable", "total"):
        assert key in result.score_details


# ---------------------------------------------------------------------------
# website_reachable=True adds 5 to verification dimension
# ---------------------------------------------------------------------------


def test_website_reachable_adds_5_to_verification():
    base = compute_score(
        company=_company(website=None),
        contacts=[],
        emails=[_email(status=EmailStatus.UNVERIFIED, mx_valid=False, contact_id=None)],
        phones=[],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    with_website = compute_score(
        company=_company(website=None),
        contacts=[],
        emails=[_email(status=EmailStatus.UNVERIFIED, mx_valid=False, contact_id=None)],
        phones=[],
        pages=[],
        website_reachable=True,
        is_suppressed=False,
    )
    assert with_website.score_details["verification_quality"] == \
           base.score_details["verification_quality"] + 5


# ---------------------------------------------------------------------------
# Verified email (VALID) adds 10 to Dim C
# ---------------------------------------------------------------------------


def test_valid_email_adds_to_verification():
    result = compute_score(
        company=_company(),
        contacts=[],
        emails=[_email(status=EmailStatus.VALID, mx_valid=True, contact_id=None)],
        phones=[],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    assert result.score_details["verification_quality"] >= 10


# ---------------------------------------------------------------------------
# Classified phone (non-UNKNOWN) adds 5 to Dim C
# ---------------------------------------------------------------------------


def test_classified_phone_adds_to_verification():
    no_phone = compute_score(
        company=_company(),
        contacts=[],
        emails=[_email(contact_id=None)],
        phones=[_phone(phone_type=PhoneType.UNKNOWN, contact_id=None)],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    with_phone = compute_score(
        company=_company(),
        contacts=[],
        emails=[_email(contact_id=None)],
        phones=[_phone(phone_type=PhoneType.MOBILE, contact_id=None)],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    assert with_phone.score_details["verification_quality"] == \
           no_phone.score_details["verification_quality"] + 5


# ---------------------------------------------------------------------------
# No pages → Dim D = 0
# ---------------------------------------------------------------------------


def test_no_pages_dim_d_is_zero():
    result = compute_score(
        company=_company(),
        contacts=[],
        emails=[_email(contact_id=None)],
        phones=[],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    assert result.score_details["scrape_quality"] == 0


# ---------------------------------------------------------------------------
# Pages with TEAM page → Dim D gets team bonus
# ---------------------------------------------------------------------------


def test_team_page_adds_to_scrape_quality():
    result = compute_score(
        company=_company(),
        contacts=[],
        emails=[_email(contact_id=None)],
        phones=[],
        pages=[_page(page_type=PageType.TEAM, word_count=200)],
        website_reachable=False,
        is_suppressed=False,
    )
    assert result.score_details["scrape_quality"] >= 9  # 5 + 4


# ---------------------------------------------------------------------------
# score < 25 → COLD band, NOT disqualified
# ---------------------------------------------------------------------------


def test_low_score_is_cold_not_disqualified():
    # Give it just one company-level phone (no emails), company name set
    result = compute_score(
        company=_company(website=None, address=None, city=None, country=None),
        contacts=[],
        emails=[],
        phones=[_phone(phone_type=PhoneType.UNKNOWN, contact_id=None)],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    # Dim B = 8 (company phone); rest 0 → total = 8 → COLD
    assert result.score < 25
    assert result.score_band == ScoreBand.COLD
    assert result.is_disqualified is False


# ---------------------------------------------------------------------------
# total in score_details matches score
# ---------------------------------------------------------------------------


def test_total_matches_score():
    result = compute_score(
        company=_company(),
        contacts=[_contact()],
        emails=[_email(status=EmailStatus.VALID, mx_valid=True, contact_id=None)],
        phones=[],
        pages=[],
        website_reachable=False,
        is_suppressed=False,
    )
    assert result.score == result.score_details["total"]
