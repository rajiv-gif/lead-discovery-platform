"""Tests for src/extraction/merge.py."""
from __future__ import annotations

from src.extraction.merge import merge
from src.extraction.models import ExtractionResult, RawContact, RawEmail, RawPhone


def _result(contacts=None, emails=None, phones=None) -> ExtractionResult:
    r = ExtractionResult()
    r.contacts = contacts or []
    r.emails = emails or []
    r.phones = phones or []
    return r


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


def test_merge_deduplicates_contacts_by_normalized_name():
    det = _result(contacts=[RawContact(full_name="Dr. John Smith")])
    llm = _result(contacts=[RawContact(full_name="Dr John Smith")])
    result = merge(det, llm)
    # Both normalize to "john smith" — only one kept
    assert len(result.contacts) == 1


def test_merge_keeps_distinct_contacts():
    det = _result(contacts=[RawContact(full_name="Dr. John Smith")])
    llm = _result(contacts=[RawContact(full_name="Dr. Jane Brown")])
    result = merge(det, llm)
    assert len(result.contacts) == 2


def test_merge_llm_none_only_det_contacts():
    det = _result(contacts=[RawContact(full_name="Dr. Alice")])
    result = merge(det, None)
    assert len(result.contacts) == 1
    assert result.contacts[0].full_name == "Dr. Alice"


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------


def test_merge_deduplicates_emails_by_address():
    det = _result(emails=[RawEmail(address="info@clinic.com")])
    llm = _result(emails=[RawEmail(address="INFO@CLINIC.COM")])
    result = merge(det, llm)
    # Both lowercase to "info@clinic.com" — only one kept
    assert len(result.emails) == 1


def test_merge_keeps_distinct_emails():
    det = _result(emails=[RawEmail(address="info@clinic.com")])
    llm = _result(emails=[RawEmail(address="admin@clinic.com")])
    result = merge(det, llm)
    assert len(result.emails) == 2


# ---------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------


def test_merge_deduplicates_phones_by_e164():
    det = _result(phones=[RawPhone(e164="+442071234567", raw="020 7123 4567")])
    llm = _result(phones=[RawPhone(e164="+442071234567", raw="+44 20 7123 4567")])
    result = merge(det, llm)
    assert len(result.phones) == 1


def test_merge_keeps_distinct_phones():
    det = _result(phones=[RawPhone(e164="+442071234567", raw="020 7123 4567")])
    llm = _result(phones=[RawPhone(e164="+441234567890", raw="01234 567890")])
    result = merge(det, llm)
    assert len(result.phones) == 2


# ---------------------------------------------------------------------------
# Combined sources
# ---------------------------------------------------------------------------


def test_merge_combines_both_sources():
    det = _result(
        contacts=[RawContact(full_name="Dr. Alice Smith")],
        emails=[RawEmail(address="info@clinic.com")],
    )
    llm = _result(
        contacts=[RawContact(full_name="Dr. Bob Jones")],
        emails=[RawEmail(address="info@clinic.com")],  # duplicate
    )
    result = merge(det, llm)
    assert len(result.contacts) == 2
    assert len(result.emails) == 1  # deduplicated
