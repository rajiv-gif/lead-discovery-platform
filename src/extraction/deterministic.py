"""Deterministic extraction from a single CompanyPage."""
from __future__ import annotations

import re
from typing import Optional

import phonenumbers
from bs4 import BeautifulSoup

from src.models.company_page import CompanyPage
from src.models.enums import PageType
from src.extraction.models import ExtractionResult, RawContact, RawEmail, RawPhone

# --- Email ---
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_GENERIC_LOCALS = frozenset([
    "info", "hello", "contact", "enquiries", "enquiry", "admin",
    "reception", "appointments", "bookings", "mail", "office",
    "practice", "team", "support", "help",
])

# --- Names ---
_PREFIX_RE = re.compile(
    r"\b(Dr\.?|Mr\.?|Mrs\.?|Ms\.?|Prof\.?|Rev\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
)
_ROLE_KEYWORDS = re.compile(
    r"\b(Dentist|Principal|Practice\s+Manager|Hygienist|Therapist|Nurse|"
    r"Receptionist|Director|Partner|Associate|Owner|Founder|"
    r"Manager|Consultant|Specialist|Coordinator|Practitioner|Surgeon|"
    r"Orthodontist|Endodontist|Periodontist|Radiologist|Physician)\b",
    re.IGNORECASE,
)
_FOOTER_CLASS_RE = re.compile(r"footer|site-footer|bottom|colophon", re.IGNORECASE)

_TEAM_CONTAINER_RE = re.compile(r"team|staff|people|about|bio|member", re.IGNORECASE)


def _is_generic_email(address: str) -> bool:
    local = address.split("@")[0].lower()
    return local in _GENERIC_LOCALS


def _extract_emails(text: str, page_type_str: str, method: str) -> list[RawEmail]:
    results = []
    for match in _EMAIL_RE.finditer(text):
        addr = match.group(0).lower()
        results.append(RawEmail(
            address=addr,
            is_generic=_is_generic_email(addr),
            source_page_type=page_type_str,
            extraction_method=method,
        ))
    return results


def _extract_phones(text: str, country_hint: str, page_type_str: str, method: str) -> list[RawPhone]:
    results = []
    # Use phonenumbers finditer approach
    for match in phonenumbers.PhoneNumberMatcher(text, country_hint):
        num = match.number
        if phonenumbers.is_valid_number(num):
            e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
            raw = match.raw_string
            results.append(RawPhone(
                e164=e164,
                raw=raw,
                source_page_type=page_type_str,
                extraction_method=method,
            ))
    return results


def _extract_contacts_from_text(text: str, page_type: PageType, page_type_str: str, method: str) -> list[RawContact]:
    """Extract name+role pairs from plain text using prefix + role heuristics."""
    contacts = []
    # Find all prefix+name matches
    for m in _PREFIX_RE.finditer(text):
        full_name = m.group(0).strip()
        # Check for role within 200 chars after the match
        surrounding = text[m.start():min(len(text), m.end() + 200)]
        has_role = bool(_ROLE_KEYWORDS.search(surrounding))

        # Page-type gating
        if page_type in (PageType.TEAM, PageType.CONTACT):
            # prefix alone sufficient on team/contact
            pass
        elif page_type in (PageType.ABOUT, PageType.HOMEPAGE):
            # require both prefix AND role
            if not has_role:
                continue
        else:
            # services/other: skip contacts
            continue

        role_match = _ROLE_KEYWORDS.search(surrounding)
        title = role_match.group(0) if role_match else None
        contacts.append(RawContact(
            full_name=full_name,
            title=title,
            source_page_type=page_type_str,
            extraction_method=method,
        ))
    return contacts


def _is_footer_element(tag) -> bool:
    """Return True if tag is or is inside a footer-like element."""
    from bs4 import Tag
    for parent in ([tag] + list(tag.parents) if hasattr(tag, 'parents') else []):
        if not isinstance(parent, Tag):
            continue
        name = getattr(parent, 'name', '') or ''
        if name == 'footer':
            return True
        classes = ' '.join(parent.get('class', []))
        id_val = parent.get('id', '') or ''
        if _FOOTER_CLASS_RE.search(classes) or _FOOTER_CLASS_RE.search(id_val):
            return True
    return False


def extract_from_page(page: CompanyPage, country_hint: str = "GB") -> ExtractionResult:
    """
    Deterministically extract contacts, emails, phones from a CompanyPage.
    Uses extracted_text for email/phone/name patterns.
    Uses raw HTML (from disk) for structural cues — if the HTML path is
    accessible; otherwise falls back to text-only extraction.
    """
    page_type = page.page_type or PageType.OTHER
    page_type_str = page_type.value
    text = page.extracted_text or ""
    method = "deterministic"

    result = ExtractionResult()

    # Skip services/other for contacts but still extract emails/phones
    result.emails = _extract_emails(text, page_type_str, method)
    result.phones = _extract_phones(text, country_hint, page_type_str, method)

    if page_type not in (PageType.SERVICES, PageType.OTHER):
        result.contacts = _extract_contacts_from_text(text, page_type, page_type_str, method)

    return result
