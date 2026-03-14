"""Tests for src/extraction/runner.py — using MagicMock session and LLMClient."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.extraction.models import ExtractionResult, RawContact, RawEmail, RawPhone
from src.extraction.runner import (
    ExtractionSummary,
    _extract_hit,
    _has_sufficient_signal,
    _select_llm_page,
)
from src.models.enums import DiscoveryHitStatus, PageType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hit(company_id=None) -> MagicMock:
    hit = MagicMock()
    hit.id = uuid.uuid4()
    hit.company_id = company_id or uuid.uuid4()
    hit.status = DiscoveryHitStatus.SCRAPED
    return hit


def _make_company(country="GB") -> MagicMock:
    company = MagicMock()
    company.id = uuid.uuid4()
    company.name = "Test Clinic"
    company.country = country
    return company


def _make_page(page_type=PageType.CONTACT, word_count=50, text="Dr. Alice Smith, Dentist") -> MagicMock:
    page = MagicMock()
    page.id = uuid.uuid4()
    page.company_id = uuid.uuid4()
    page.page_type = page_type
    page.word_count = word_count
    page.extracted_text = text
    return page


def _make_session(company=None, pages=None) -> MagicMock:
    session = MagicMock()
    session.get.return_value = company
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = pages or []
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute.return_value = execute_result
    return session


# ---------------------------------------------------------------------------
# _select_llm_page
# ---------------------------------------------------------------------------


def test_select_llm_page_prefers_team():
    team_page = _make_page(PageType.TEAM, word_count=100)
    contact_page = _make_page(PageType.CONTACT, word_count=200)
    result = _select_llm_page([contact_page, team_page])
    assert result is team_page


def test_select_llm_page_falls_back_to_contact():
    contact_page = _make_page(PageType.CONTACT, word_count=50)
    homepage = _make_page(PageType.HOMEPAGE, word_count=200)
    result = _select_llm_page([homepage, contact_page])
    assert result is contact_page


def test_select_llm_page_skips_low_word_count():
    short_team = _make_page(PageType.TEAM, word_count=10)
    about_page = _make_page(PageType.ABOUT, word_count=50)
    result = _select_llm_page([short_team, about_page])
    assert result is about_page


def test_select_llm_page_returns_none_when_no_candidates():
    homepage = _make_page(PageType.HOMEPAGE, word_count=200)
    result = _select_llm_page([homepage])
    assert result is None


# ---------------------------------------------------------------------------
# _has_sufficient_signal
# ---------------------------------------------------------------------------


def test_has_sufficient_signal_with_email():
    page = _make_page(text="Email us at info@clinic.com")
    assert _has_sufficient_signal(page) is True


def test_has_sufficient_signal_with_phone():
    page = _make_page(text="Call 020 7123 4567 today")
    assert _has_sufficient_signal(page) is True


def test_has_sufficient_signal_with_name():
    page = _make_page(text="Dr John Smith leads our team")
    assert _has_sufficient_signal(page) is True


def test_has_sufficient_signal_no_signal():
    page = _make_page(text="welcome to our clinic")
    assert _has_sufficient_signal(page) is False


# ---------------------------------------------------------------------------
# _extract_hit — skip cases
# ---------------------------------------------------------------------------


def test_extract_hit_no_company_id_skipped():
    hit = _make_hit()
    hit.company_id = None
    session = MagicMock()
    summary = ExtractionSummary()

    _extract_hit(session, hit, None, MagicMock(), 1024, summary)

    assert hit.status == DiscoveryHitStatus.SKIPPED
    assert summary.hits_skipped == 1
    assert summary.hits_processed == 1


def test_extract_hit_company_not_found_skipped():
    hit = _make_hit()
    session = MagicMock()
    session.get.return_value = None  # company not found
    summary = ExtractionSummary()

    _extract_hit(session, hit, None, MagicMock(), 1024, summary)

    assert hit.status == DiscoveryHitStatus.SKIPPED
    assert summary.hits_skipped == 1


def test_extract_hit_no_pages_skipped():
    company = _make_company()
    hit = _make_hit(company_id=company.id)

    session = MagicMock()
    session.get.return_value = company

    # execute for pages returns empty list
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute.return_value = execute_result

    summary = ExtractionSummary()
    _extract_hit(session, hit, None, MagicMock(), 1024, summary)

    assert hit.status == DiscoveryHitStatus.SKIPPED
    assert summary.hits_skipped == 1


# ---------------------------------------------------------------------------
# _extract_hit — extraction cases
# ---------------------------------------------------------------------------


def test_extract_hit_with_pages_sets_extracted_status():
    company = _make_company()
    hit = _make_hit(company_id=company.id)
    page = _make_page(PageType.CONTACT, word_count=50, text="info@clinic.com")

    session = MagicMock()
    session.get.return_value = company
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [page]
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    # For persist queries (email/phone existence), return empty
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.side_effect = [execute_result] + [not_found] * 20

    summary = ExtractionSummary()
    _extract_hit(session, hit, None, MagicMock(), 1024, summary)

    assert hit.status == DiscoveryHitStatus.EXTRACTED
    assert summary.hits_processed == 1


def test_llm_not_triggered_when_det_contacts_found():
    company = _make_company()
    hit = _make_hit(company_id=company.id)
    # Page with a Dr. prefix → deterministic will find a contact
    page = _make_page(PageType.TEAM, word_count=100, text="Dr. Alice Smith leads our team.")

    session = MagicMock()
    session.get.return_value = company
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [page]
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.side_effect = [execute_result] + [not_found] * 20

    llm_client = MagicMock()
    summary = ExtractionSummary()

    _extract_hit(session, hit, llm_client, MagicMock(), 1024, summary)

    # LLM should NOT have been called
    llm_client.complete.assert_not_called()


def test_llm_triggered_when_no_det_contacts():
    company = _make_company()
    hit = _make_hit(company_id=company.id)
    # Page with no prefix names but has signal (email)
    page = _make_page(PageType.TEAM, word_count=50, text="info@clinic.com Call us on 020 7123 4567")

    session = MagicMock()
    session.get.return_value = company
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [page]
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.side_effect = [execute_result] + [not_found] * 20

    llm_client = MagicMock()

    with patch("src.extraction.runner.call_llm") as mock_call_llm:
        mock_call_llm.return_value = ExtractionResult()
        summary = ExtractionSummary()
        _extract_hit(session, hit, llm_client, MagicMock(), 1024, summary)
        mock_call_llm.assert_called_once()


def test_llm_failure_returns_none_still_extracts():
    """If LLM returns None (failure), extraction still completes without error."""
    company = _make_company()
    hit = _make_hit(company_id=company.id)
    page = _make_page(PageType.TEAM, word_count=50, text="info@clinic.com")

    session = MagicMock()
    session.get.return_value = company
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [page]
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.side_effect = [execute_result] + [not_found] * 20

    llm_client = MagicMock()

    with patch("src.extraction.runner.call_llm", return_value=None):
        summary = ExtractionSummary()
        _extract_hit(session, hit, llm_client, MagicMock(), 1024, summary)

    # Should be EXTRACTED, not FAILED
    assert hit.status == DiscoveryHitStatus.EXTRACTED
    assert summary.hits_failed == 0


# ---------------------------------------------------------------------------
# ExtractionSummary counts
# ---------------------------------------------------------------------------


def test_extraction_summary_counts():
    summary = ExtractionSummary()
    summary.hits_processed = 5
    summary.hits_with_data = 3
    summary.hits_zero_data = 1
    summary.hits_failed = 1
    summary.hits_skipped = 0
    summary.record_error("hit=abc: timeout")

    assert summary.errors == 1
    assert len(summary.error_details) == 1
    assert "timeout" in summary.error_details[0]
