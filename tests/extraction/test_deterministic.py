"""Tests for src/extraction/deterministic.py."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from src.extraction.deterministic import extract_from_page
from src.models.enums import PageType


def _make_page(text: str, page_type: PageType = PageType.CONTACT) -> MagicMock:
    page = MagicMock()
    page.extracted_text = text
    page.page_type = page_type
    page.company_id = uuid.uuid4()
    page.id = uuid.uuid4()
    return page


# ---------------------------------------------------------------------------
# Email extraction
# ---------------------------------------------------------------------------


def test_email_extraction_generic():
    page = _make_page("Contact us at info@example.com for appointments.")
    result = extract_from_page(page, "GB")
    assert len(result.emails) == 1
    assert result.emails[0].address == "info@example.com"
    assert result.emails[0].is_generic is True


def test_email_extraction_named():
    page = _make_page("Email Dr. Smith at jsmith@clinic.co.uk")
    result = extract_from_page(page, "GB")
    assert len(result.emails) == 1
    assert result.emails[0].address == "jsmith@clinic.co.uk"
    assert result.emails[0].is_generic is False


def test_email_extraction_multiple():
    page = _make_page("info@clinic.com or admin@clinic.com")
    result = extract_from_page(page, "GB")
    assert len(result.emails) == 2
    addresses = {e.address for e in result.emails}
    assert "info@clinic.com" in addresses
    assert "admin@clinic.com" in addresses


# ---------------------------------------------------------------------------
# Phone extraction
# ---------------------------------------------------------------------------


def test_phone_extraction_valid_uk():
    page = _make_page("Call us on 020 7123 4567.")
    result = extract_from_page(page, "GB")
    assert len(result.phones) == 1
    assert result.phones[0].e164 == "+442071234567"
    assert result.phones[0].raw == "020 7123 4567"


def test_phone_extraction_invalid_skipped():
    page = _make_page("Call us on 123 for appointments.")
    result = extract_from_page(page, "GB")
    assert result.phones == []


# ---------------------------------------------------------------------------
# Contact extraction
# ---------------------------------------------------------------------------


def test_contact_extraction_team_page_prefix_sufficient():
    text = "Dr. Sarah Jones leads our team."
    page = _make_page(text, PageType.TEAM)
    result = extract_from_page(page, "GB")
    assert len(result.contacts) == 1
    assert "Sarah Jones" in result.contacts[0].full_name


def test_contact_extraction_about_page_requires_role():
    # Prefix without role on ABOUT page → no contact
    text = "Dr. Jane Brown is part of our team."
    page = _make_page(text, PageType.ABOUT)
    result = extract_from_page(page, "GB")
    assert result.contacts == []


def test_contact_extraction_about_page_with_role():
    text = "Dr. Jane Brown, our principal Dentist, has 20 years experience."
    page = _make_page(text, PageType.ABOUT)
    result = extract_from_page(page, "GB")
    assert len(result.contacts) == 1
    assert "Jane Brown" in result.contacts[0].full_name
    assert result.contacts[0].title is not None


def test_contact_extraction_services_page_returns_no_contacts():
    text = "Dr. John Smith offers cosmetic Dentist services."
    page = _make_page(text, PageType.SERVICES)
    result = extract_from_page(page, "GB")
    assert result.contacts == []


def test_contact_extraction_other_page_returns_no_contacts():
    text = "Dr. John Smith offers cosmetic Dentist services."
    page = _make_page(text, PageType.OTHER)
    result = extract_from_page(page, "GB")
    assert result.contacts == []


# ---------------------------------------------------------------------------
# No text → empty result
# ---------------------------------------------------------------------------


def test_no_text_returns_empty_result():
    page = _make_page("", PageType.CONTACT)
    result = extract_from_page(page, "GB")
    assert result.contacts == []
    assert result.emails == []
    assert result.phones == []


def test_none_text_returns_empty_result():
    page = _make_page(None, PageType.CONTACT)
    page.extracted_text = None
    result = extract_from_page(page, "GB")
    assert result.contacts == []
    assert result.emails == []
    assert result.phones == []
