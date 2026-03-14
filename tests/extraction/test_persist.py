"""Tests for src/extraction/persist.py — using MagicMock session."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, call, patch

import pytest

from src.extraction.models import ExtractionResult, RawContact, RawEmail, RawPhone
from src.extraction.persist import persist_result
from src.models.enums import EmailStatus, PhoneType


def _make_session(
    existing_contact=None,
    existing_email=None,
    existing_phone=None,
    has_company_email=False,
    has_company_phone=False,
) -> MagicMock:
    """Build a mock session that returns controlled query results."""
    session = MagicMock()

    # We need to track calls to session.execute and return appropriate values.
    # The persist_result function issues selects in this order:
    #   1. select(Contact) for each contact
    #   2. select(Email).where(... contact_id is None)  — has_company_email check
    #   3. select(Email).where(... address==) for each email
    #   4. select(Phone).where(... contact_id is None) — has_company_phone check
    #   5. select(Phone).where(... number==) for each phone

    # Use a side_effect list so successive calls return different values.
    # Subclass MagicMock to make .scalars().all() / .scalar_one_or_none() / .first() work.

    contact_scalar = MagicMock()
    contact_scalar.scalar_one_or_none.return_value = existing_contact

    company_email_result = MagicMock()
    company_email_result.first.return_value = object() if has_company_email else None

    email_scalar = MagicMock()
    email_scalar.scalar_one_or_none.return_value = existing_email

    company_phone_result = MagicMock()
    company_phone_result.first.return_value = object() if has_company_phone else None

    phone_scalar = MagicMock()
    phone_scalar.scalar_one_or_none.return_value = existing_phone

    # Return results in order
    session.execute.side_effect = [
        contact_scalar,        # contact existence check
        company_email_result,  # has_company_email check
        email_scalar,          # email existence check
        company_phone_result,  # has_company_phone check
        phone_scalar,          # phone existence check
    ]

    return session


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


def test_persist_creates_new_contact():
    session = MagicMock()
    # All queries return "not found"
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.return_value = not_found

    result = ExtractionResult()
    result.contacts = [RawContact(full_name="Dr. John Smith", title="Dentist")]
    company_id = uuid.uuid4()

    summary = persist_result(session, company_id, result)

    assert summary.contacts_created == 1
    added_contact = session.add.call_args_list[0][0][0]
    assert added_contact.full_name == "Dr. John Smith"
    assert added_contact.first_name == "Dr."
    assert added_contact.last_name == "John Smith"
    assert added_contact.source == "company_page:deterministic"


def test_persist_dedup_skips_existing_contact():
    session = MagicMock()
    existing_contact = MagicMock()
    existing_contact.id = uuid.uuid4()
    existing_response = MagicMock()
    existing_response.scalar_one_or_none.return_value = existing_contact
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.side_effect = [existing_response, not_found, not_found, not_found, not_found]

    result = ExtractionResult()
    result.contacts = [RawContact(full_name="Dr. John Smith")]
    company_id = uuid.uuid4()

    summary = persist_result(session, company_id, result)

    assert summary.contacts_created == 0


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------


def test_persist_creates_email_with_company_id():
    session = MagicMock()
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.return_value = not_found

    result = ExtractionResult()
    result.emails = [RawEmail(address="info@clinic.com", is_generic=True)]
    company_id = uuid.uuid4()

    summary = persist_result(session, company_id, result)

    assert summary.emails_created == 1
    added_email = session.add.call_args_list[0][0][0]
    assert added_email.company_id == company_id
    assert added_email.address == "info@clinic.com"


def test_persist_dedup_skips_existing_email():
    session = MagicMock()
    existing_email = MagicMock()
    existing_email_response = MagicMock()
    existing_email_response.scalar_one_or_none.return_value = existing_email
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.side_effect = [not_found, existing_email_response, not_found, not_found]

    result = ExtractionResult()
    result.emails = [RawEmail(address="info@clinic.com", is_generic=True)]
    company_id = uuid.uuid4()

    summary = persist_result(session, company_id, result)

    assert summary.emails_created == 0


def test_persist_generic_email_has_no_contact_id():
    session = MagicMock()
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.return_value = not_found

    result = ExtractionResult()
    result.emails = [RawEmail(address="info@clinic.com", is_generic=True)]
    company_id = uuid.uuid4()

    persist_result(session, company_id, result)

    added_email = session.add.call_args_list[0][0][0]
    assert added_email.contact_id is None


# ---------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------


def test_persist_creates_phone_with_e164():
    session = MagicMock()
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.return_value = not_found

    result = ExtractionResult()
    result.phones = [RawPhone(e164="+442071234567", raw="020 7123 4567")]
    company_id = uuid.uuid4()

    summary = persist_result(session, company_id, result)

    assert summary.phones_created == 1
    added_phone = session.add.call_args_list[0][0][0]
    assert added_phone.number == "+442071234567"
    assert added_phone.raw_number == "020 7123 4567"


def test_persist_dedup_skips_existing_phone():
    session = MagicMock()
    existing_phone = MagicMock()
    existing_phone_response = MagicMock()
    existing_phone_response.scalar_one_or_none.return_value = existing_phone
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.side_effect = [not_found, not_found, existing_phone_response]

    result = ExtractionResult()
    result.phones = [RawPhone(e164="+442071234567", raw="020 7123 4567")]
    company_id = uuid.uuid4()

    summary = persist_result(session, company_id, result)

    assert summary.phones_created == 0


def test_persist_unnormalisable_phone_skipped():
    session = MagicMock()
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    not_found.first.return_value = None
    session.execute.return_value = not_found

    result = ExtractionResult()
    # e164 and raw are both garbage strings that can't be parsed as phone numbers
    result.phones = [RawPhone(e164="NOT_A_PHONE", raw="NOT_A_PHONE")]
    company_id = uuid.uuid4()

    summary = persist_result(session, company_id, result)

    assert summary.phones_created == 0
