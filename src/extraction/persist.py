"""Write ExtractionResult into existing Contact / Email / Phone ORM rows."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional
import uuid

import phonenumbers
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.extraction.models import ExtractionResult, normalize_name_key, split_name
from src.models.contact import Contact
from src.models.email import Email
from src.models.enums import EmailStatus, PhoneType
from src.models.phone import Phone

log = logging.getLogger(__name__)


@dataclass
class PersistSummary:
    contacts_created: int = 0
    emails_created: int = 0
    phones_created: int = 0


def _normalize_e164(raw: str, country_hint: str = "GB") -> Optional[str]:
    """Re-normalise a raw or already-E164 phone string. Returns None on failure."""
    try:
        num = phonenumbers.parse(raw, country_hint)
        if phonenumbers.is_valid_number(num):
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    return None


def persist_result(
    session: Session,
    company_id: uuid.UUID,
    result: ExtractionResult,
    country_hint: str = "GB",
) -> PersistSummary:
    summary = PersistSummary()

    # --- Contacts ---
    # Build a map: normalized_name_key → Contact (for phone/email linking)
    name_to_contact: dict[str, Contact] = {}

    for rc in result.contacts:
        nk = normalize_name_key(rc.full_name)
        # Dedup: check existing row
        existing = session.execute(
            select(Contact).where(
                Contact.company_id == company_id,
                Contact.full_name == rc.full_name,
            )
        ).scalar_one_or_none()

        # Also check by normalized key against already-inserted rows this run
        if existing is None and nk in name_to_contact:
            existing = name_to_contact[nk]

        if existing is None:
            first_name, last_name = split_name(rc.full_name)
            contact = Contact(
                company_id=company_id,
                full_name=rc.full_name,
                first_name=first_name,
                last_name=last_name,
                title=rc.title,
                source=f"company_page:{rc.extraction_method}",
            )
            session.add(contact)
            session.flush()  # get contact.id
            summary.contacts_created += 1
            name_to_contact[nk] = contact
        else:
            name_to_contact[nk] = existing

    # --- Emails ---
    has_company_email = session.execute(
        select(Email).where(
            Email.company_id == company_id,
            Email.contact_id.is_(None),
        )
    ).first() is not None

    for re_ in result.emails:
        # Dedup by (company_id, address)
        existing_email = session.execute(
            select(Email).where(
                Email.company_id == company_id,
                Email.address == re_.address,
            )
        ).scalar_one_or_none()
        if existing_email is not None:
            continue

        contact_id: Optional[uuid.UUID] = None
        if not re_.is_generic and re_.contact_full_name:
            nk = normalize_name_key(re_.contact_full_name)
            c = name_to_contact.get(nk)
            if c:
                contact_id = c.id

        is_primary = not has_company_email and re_.is_generic and contact_id is None
        email_row = Email(
            company_id=company_id,
            contact_id=contact_id,
            address=re_.address,
            status=EmailStatus.UNVERIFIED,
            is_primary=is_primary,
        )
        session.add(email_row)
        if is_primary:
            has_company_email = True
        summary.emails_created += 1

    # --- Phones ---
    has_company_phone = session.execute(
        select(Phone).where(
            Phone.company_id == company_id,
            Phone.contact_id.is_(None),
        )
    ).first() is not None

    for rp in result.phones:
        e164 = _normalize_e164(rp.e164) or _normalize_e164(rp.raw)
        if not e164:
            log.debug("Skipping unnormalisable phone: %s", rp.raw)
            continue

        existing_phone = session.execute(
            select(Phone).where(
                Phone.company_id == company_id,
                Phone.number == e164,
            )
        ).scalar_one_or_none()
        if existing_phone is not None:
            continue

        contact_id = None
        if rp.contact_full_name:
            nk = normalize_name_key(rp.contact_full_name)
            c = name_to_contact.get(nk)
            if c:
                contact_id = c.id

        is_primary = not has_company_phone and contact_id is None
        phone_row = Phone(
            company_id=company_id,
            contact_id=contact_id,
            number=e164,
            raw_number=rp.raw,
            phone_type=PhoneType.UNKNOWN,
            is_primary=is_primary,
        )
        session.add(phone_row)
        if is_primary:
            has_company_phone = True
        summary.phones_created += 1

    return summary
