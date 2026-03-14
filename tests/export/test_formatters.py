"""Tests for src/export/formatters.py — pure function tests, no DB."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from src.export.formatters import (
    CompanyData,
    build_company_fallback_rows,
    build_full_leads_rows,
    build_named_contacts_rows,
    is_company_suppressed,
    is_exportable_email,
)
from src.models.enums import EmailStatus, ScoreBand


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _company(name="Acme Ltd", domain="acme.com", website="https://acme.com", **kwargs):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.name = name
    c.domain = domain
    c.website = website
    c.address = "1 High St"
    c.city = "London"
    c.country = "GB"
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def _lead(score=60.0, band=ScoreBand.WARM):
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.score = score
    lead.score_band = band
    lead.review_decided_at = None
    return lead


def _contact(
    company_id=None,
    first_name=None,
    last_name=None,
    full_name=None,
    title=None,
):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.company_id = company_id or uuid.uuid4()
    c.first_name = first_name
    c.last_name = last_name
    c.full_name = full_name
    c.title = title
    return c


def _email(
    company_id=None,
    contact_id=None,
    address="test@acme.com",
    status=EmailStatus.VALID,
    is_primary=False,
):
    e = MagicMock()
    e.id = uuid.uuid4()
    e.company_id = company_id or uuid.uuid4()
    e.contact_id = contact_id
    e.address = address
    e.status = status
    e.is_primary = is_primary
    return e


def _phone(company_id=None, contact_id=None, number="+441234567890", is_primary=False):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.company_id = company_id or uuid.uuid4()
    p.contact_id = contact_id
    p.number = number
    p.is_primary = is_primary
    return p


def _make_cd(company=None, contacts=None, emails=None, phones=None):
    if company is None:
        company = _company()
    lead = _lead()
    return CompanyData(
        company=company,
        lead=lead,
        contacts=contacts or [],
        emails=emails or [],
        phones=phones or [],
    )


# ---------------------------------------------------------------------------
# is_exportable_email tests
# ---------------------------------------------------------------------------


def test_exportable_email_valid_not_suppressed():
    assert is_exportable_email("test@acme.com", EmailStatus.VALID, set(), set()) is True


def test_exportable_email_invalid_status():
    assert is_exportable_email("test@acme.com", EmailStatus.INVALID, set(), set()) is False


def test_exportable_email_address_suppressed():
    assert is_exportable_email(
        "test@acme.com", EmailStatus.VALID, {"test@acme.com"}, set()
    ) is False


def test_exportable_email_domain_suppressed():
    assert is_exportable_email(
        "test@acme.com", EmailStatus.VALID, set(), {"acme.com"}
    ) is False


# ---------------------------------------------------------------------------
# Named contacts formatter tests
# ---------------------------------------------------------------------------


def test_named_contacts_valid_email_included():
    company = _company()
    contact = _contact(company_id=company.id)
    email = _email(company_id=company.id, contact_id=contact.id, address="john@acme.com")

    cd = CompanyData(company=company, lead=_lead(), contacts=[contact], emails=[email], phones=[])
    rows = build_named_contacts_rows([cd], set(), set(), set())

    assert len(rows) == 1
    assert rows[0]["email"] == "john@acme.com"


def test_named_contacts_invalid_email_excluded():
    company = _company()
    contact = _contact(company_id=company.id)
    email = _email(
        company_id=company.id,
        contact_id=contact.id,
        address="bad@acme.com",
        status=EmailStatus.INVALID,
    )

    cd = CompanyData(company=company, lead=_lead(), contacts=[contact], emails=[email], phones=[])
    rows = build_named_contacts_rows([cd], set(), set(), set())

    assert len(rows) == 0


def test_named_contacts_address_in_suppressed_emails_excluded():
    company = _company()
    contact = _contact(company_id=company.id)
    email = _email(company_id=company.id, contact_id=contact.id, address="john@acme.com")

    cd = CompanyData(company=company, lead=_lead(), contacts=[contact], emails=[email], phones=[])
    rows = build_named_contacts_rows([cd], {"john@acme.com"}, set(), set())

    assert len(rows) == 0


def test_named_contacts_domain_in_suppressed_domains_excluded():
    company = _company()
    contact = _contact(company_id=company.id)
    email = _email(company_id=company.id, contact_id=contact.id, address="john@acme.com")

    cd = CompanyData(company=company, lead=_lead(), contacts=[contact], emails=[email], phones=[])
    rows = build_named_contacts_rows([cd], set(), {"acme.com"}, set())

    assert len(rows) == 0


def test_named_contacts_suppressed_company_all_excluded():
    company = _company(name="Acme Ltd")
    contact = _contact(company_id=company.id)
    email = _email(company_id=company.id, contact_id=contact.id, address="john@acme.com")

    cd = CompanyData(company=company, lead=_lead(), contacts=[contact], emails=[email], phones=[])
    rows = build_named_contacts_rows([cd], set(), set(), {"acme ltd"})

    assert len(rows) == 0


def test_named_contacts_within_run_email_dedup():
    """Same email address for two contacts → only one row."""
    company = _company()
    contact1 = _contact(company_id=company.id, full_name="Alice Smith")
    contact2 = _contact(company_id=company.id, full_name="Bob Jones")
    shared_email_addr = "shared@acme.com"
    email1 = _email(
        company_id=company.id,
        contact_id=contact1.id,
        address=shared_email_addr,
        status=EmailStatus.VALID,
    )
    email2 = _email(
        company_id=company.id,
        contact_id=contact2.id,
        address=shared_email_addr,
        status=EmailStatus.VALID,
    )

    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=[contact1, contact2],
        emails=[email1, email2],
        phones=[],
    )
    rows = build_named_contacts_rows([cd], set(), set(), set())

    assert len(rows) == 1


def test_named_contacts_sort_order_valid_first():
    """Contact with VALID email comes before contact with UNVERIFIED email."""
    company = _company()
    contact_unverified = _contact(company_id=company.id, full_name="Bob Jones")
    contact_valid = _contact(company_id=company.id, full_name="Alice Smith")

    email_unverified = _email(
        company_id=company.id,
        contact_id=contact_unverified.id,
        address="bob@acme.com",
        status=EmailStatus.UNVERIFIED,
    )
    email_valid = _email(
        company_id=company.id,
        contact_id=contact_valid.id,
        address="alice@acme.com",
        status=EmailStatus.VALID,
    )

    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=[contact_unverified, contact_valid],
        emails=[email_unverified, email_valid],
        phones=[],
    )
    rows = build_named_contacts_rows([cd], set(), set(), set())

    assert len(rows) == 2
    assert rows[0]["email"] == "alice@acme.com"
    assert rows[1]["email"] == "bob@acme.com"


def test_named_contacts_first_name_fallback_from_full_name():
    """When first_name is None, extract from full_name."""
    company = _company()
    contact = _contact(
        company_id=company.id,
        first_name=None,
        last_name=None,
        full_name="Jane Doe",
    )
    email = _email(company_id=company.id, contact_id=contact.id, address="jane@acme.com")

    cd = CompanyData(company=company, lead=_lead(), contacts=[contact], emails=[email], phones=[])
    rows = build_named_contacts_rows([cd], set(), set(), set())

    assert len(rows) == 1
    assert rows[0]["first_name"] == "Jane"
    assert rows[0]["last_name"] == "Doe"


# ---------------------------------------------------------------------------
# Company fallback formatter tests
# ---------------------------------------------------------------------------


def test_company_fallback_triggers_when_all_contact_emails_invalid():
    """Company-level email used when all contact emails are INVALID."""
    company = _company()
    contact = _contact(company_id=company.id)
    contact_email = _email(
        company_id=company.id,
        contact_id=contact.id,
        address="bad@acme.com",
        status=EmailStatus.INVALID,
    )
    company_email = _email(
        company_id=company.id,
        contact_id=None,
        address="info@acme.com",
        status=EmailStatus.VALID,
    )

    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=[contact],
        emails=[contact_email, company_email],
        phones=[],
    )
    rows = build_company_fallback_rows([cd], set(), set(), set())

    assert len(rows) == 1
    assert rows[0]["email"] == "info@acme.com"


def test_company_fallback_triggers_when_no_contacts_only_company_email():
    """Company fallback triggers when there are no contacts at all, only company-level email."""
    company = _company()
    company_email = _email(
        company_id=company.id,
        contact_id=None,
        address="info@acme.com",
        status=EmailStatus.VALID,
    )

    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=[],  # no contacts
        emails=[company_email],
        phones=[],
    )
    rows = build_company_fallback_rows([cd], set(), set(), set())

    assert len(rows) == 1
    assert rows[0]["email"] == "info@acme.com"


def test_company_fallback_excluded_when_company_suppressed():
    company = _company(name="BlockedCo")
    company_email = _email(
        company_id=company.id,
        contact_id=None,
        address="info@blocked.com",
        status=EmailStatus.VALID,
    )

    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=[],
        emails=[company_email],
        phones=[],
    )
    rows = build_company_fallback_rows([cd], set(), set(), {"blockedco"})

    assert len(rows) == 0


def test_company_fallback_excluded_when_no_usable_email_or_phone():
    """If no company-level email and no phone, skip fallback."""
    company = _company()
    contact = _contact(company_id=company.id)
    contact_email = _email(
        company_id=company.id,
        contact_id=contact.id,
        address="bad@acme.com",
        status=EmailStatus.INVALID,
    )

    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=[contact],
        emails=[contact_email],
        phones=[],
    )
    rows = build_company_fallback_rows([cd], set(), set(), set())

    assert len(rows) == 0


def test_company_fallback_primary_email_selected_correctly():
    """is_primary=True email is preferred over non-primary."""
    company = _company()
    email_secondary = _email(
        company_id=company.id,
        contact_id=None,
        address="other@acme.com",
        status=EmailStatus.VALID,
        is_primary=False,
    )
    email_primary = _email(
        company_id=company.id,
        contact_id=None,
        address="info@acme.com",
        status=EmailStatus.VALID,
        is_primary=True,
    )

    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=[],
        emails=[email_secondary, email_primary],
        phones=[],
    )
    rows = build_company_fallback_rows([cd], set(), set(), set())

    assert len(rows) == 1
    assert rows[0]["email"] == "info@acme.com"


# ---------------------------------------------------------------------------
# Full leads formatter tests
# ---------------------------------------------------------------------------


def test_full_leads_suppressed_true_when_company_domain_suppressed():
    company = _company(domain="blocked.com")
    cd = _make_cd(company=company)
    rows = build_full_leads_rows([cd], set(), {"blocked.com"}, set())

    assert len(rows) == 1
    assert rows[0]["suppressed"] is True


def test_full_leads_suppressed_true_when_any_contact_email_suppressed():
    company = _company()
    contact = _contact(company_id=company.id)
    email = _email(
        company_id=company.id,
        contact_id=contact.id,
        address="john@acme.com",
        status=EmailStatus.VALID,
    )
    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=[contact],
        emails=[email],
        phones=[],
    )
    rows = build_full_leads_rows([cd], {"john@acme.com"}, set(), set())

    assert len(rows) == 1
    assert rows[0]["suppressed"] is True


def test_full_leads_all_companies_included_regardless_of_suppression():
    """Management view: ALL companies appear, suppression only sets a flag."""
    company1 = _company(name="Good Co", domain="good.com")
    company2 = _company(name="Bad Co", domain="bad.com")
    cd1 = _make_cd(company=company1)
    cd2 = _make_cd(company=company2)

    rows = build_full_leads_rows([cd1, cd2], set(), {"bad.com"}, set())

    assert len(rows) == 2


def test_full_leads_named_contacts_semicolon_joined_top_3():
    company = _company()
    contacts = [
        _contact(company_id=company.id, full_name="Alice Smith", title="CEO"),
        _contact(company_id=company.id, full_name="Bob Jones", title=None),
        _contact(company_id=company.id, full_name="Carol White", title="CFO"),
        _contact(company_id=company.id, full_name="Dave Brown", title=None),
    ]
    cd = CompanyData(
        company=company,
        lead=_lead(),
        contacts=contacts,
        emails=[],
        phones=[],
    )
    rows = build_full_leads_rows([cd], set(), set(), set())

    assert len(rows) == 1
    named = rows[0]["named_contacts"]
    parts = named.split("; ")
    assert len(parts) == 3  # top 3 only
    assert "Alice Smith (CEO)" in parts
    assert "Bob Jones" in parts
    assert "Carol White (CFO)" in parts
