"""Export formatters — pure functions that build CSV row dicts from CompanyData.

Three output formats:
  1. Named contacts  — one row per contact with exportable email
  2. Company fallback — one row per company when no named contact qualifies
  3. Full leads       — management view; one row per company, includes all data

No database access in this module. All data is passed in as plain objects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from src.models.company import Company
from src.models.company_lead import CompanyLead
from src.models.contact import Contact
from src.models.email import Email
from src.models.enums import EmailStatus, SuppressionType
from src.models.phone import Phone
from src.models.suppression_list import SuppressionList

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field name lists
# ---------------------------------------------------------------------------

NAMED_CONTACTS_FIELDS = [
    "first_name",
    "last_name",
    "email",
    "title",
    "company_name",
    "website",
    "city",
    "country",
    "phone",
    "score",
    "score_band",
    "lead_id",
]

COMPANY_FALLBACK_FIELDS = [
    "company_name",
    "website",
    "email",
    "phone",
    "address",
    "city",
    "country",
    "score",
    "score_band",
    "lead_id",
]

FULL_LEADS_FIELDS = [
    "company_name",
    "website",
    "website_status",
    "website_gap_score",
    "email",
    "phone",
    "address",
    "city",
    "country",
    "score",
    "score_band",
    "contact_count",
    "exportable_email_count",
    "company_email_count",
    "named_contacts",
    "exportable_emails",
    "review_approved_at",
    "lead_id",
    "suppressed",
]


# ---------------------------------------------------------------------------
# CompanyData container
# ---------------------------------------------------------------------------


@dataclass
class CompanyData:
    company: Company
    lead: CompanyLead
    contacts: list[Contact]
    emails: list[Email]
    phones: list[Phone]


# ---------------------------------------------------------------------------
# Suppression set loader
# ---------------------------------------------------------------------------


def load_suppression_sets(session) -> tuple[set[str], set[str], set[str]]:
    """Load suppression sets from the DB.

    Returns:
        (suppressed_emails, suppressed_domains, suppressed_companies)
        All strings are lowercased.
    """
    rows = session.execute(select(SuppressionList)).scalars().all()

    suppressed_emails: set[str] = set()
    suppressed_domains: set[str] = set()
    suppressed_companies: set[str] = set()

    for row in rows:
        val = row.value.lower()
        if row.suppression_type == SuppressionType.EMAIL:
            suppressed_emails.add(val)
        elif row.suppression_type == SuppressionType.DOMAIN:
            suppressed_domains.add(val)
        elif row.suppression_type == SuppressionType.COMPANY:
            suppressed_companies.add(val)
        # PHONE type intentionally ignored for email-focused export suppression

    return suppressed_emails, suppressed_domains, suppressed_companies


# ---------------------------------------------------------------------------
# Email exportability predicate
# ---------------------------------------------------------------------------


def is_exportable_email(
    address: str,
    status: EmailStatus,
    suppressed_emails: set[str],
    suppressed_domains: set[str],
) -> bool:
    """Return True if this email address may be included in an export.

    Returns False if:
      - status is INVALID
      - address (lowercased) is in suppressed_emails
      - domain of address is in suppressed_domains
    """
    if status == EmailStatus.INVALID:
        return False

    addr_lower = address.lower()
    if addr_lower in suppressed_emails:
        return False

    domain = addr_lower.split("@", 1)[-1] if "@" in addr_lower else ""
    if domain in suppressed_domains:
        return False

    return True


# ---------------------------------------------------------------------------
# Company-level suppression check
# ---------------------------------------------------------------------------


def is_company_suppressed(
    company: Company,
    all_emails: list[Email],
    suppressed_emails: set[str],
    suppressed_domains: set[str],
    suppressed_companies: set[str],
) -> bool:
    """Return True if this company should be suppressed entirely.

    Checks:
      1. company.domain in suppressed_domains
      2. company.name (lower) in suppressed_companies
      3. any email address for the company in suppressed_emails
      4. domain of any email for the company in suppressed_domains
    """
    # 1. domain-level block
    if company.domain and company.domain.lower() in suppressed_domains:
        return True

    # 2. company name block
    if company.name and company.name.lower() in suppressed_companies:
        return True

    # 3 & 4. per-email checks
    for email in all_emails:
        addr_lower = email.address.lower()
        if addr_lower in suppressed_emails:
            return True
        domain = addr_lower.split("@", 1)[-1] if "@" in addr_lower else ""
        if domain in suppressed_domains:
            return True

    return False


# ---------------------------------------------------------------------------
# Name parsing helper
# ---------------------------------------------------------------------------


def _split_name(contact: Contact) -> tuple[str, str]:
    """Return (first_name, last_name) for a contact.

    Priority:
      - Use contact.first_name / contact.last_name if set.
      - Else split contact.full_name on whitespace.
      - Else return ("", "").
    """
    if contact.first_name or contact.last_name:
        return (contact.first_name or ""), (contact.last_name or "")

    full = contact.full_name or ""
    parts = full.split(None, 1)
    if len(parts) == 0:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Named contacts formatter
# ---------------------------------------------------------------------------


def build_named_contacts_rows(
    companies_data: list[CompanyData],
    suppressed_emails: set[str],
    suppressed_domains: set[str],
    suppressed_companies: set[str],
) -> list[dict]:
    """Build one CSV row per contact that has an exportable email.

    Skips:
      - Suppressed companies entirely.
      - Contacts with no exportable email.
      - Contacts whose best email has already appeared in this run (dedup).

    Sort order within company:
      1. Contacts with a VALID email
      2. Contacts with an UNVERIFIED (or other non-INVALID) email
      3. Contacts with a title (tiebreak)
    """
    rows: list[dict] = []
    seen_addresses: set[str] = set()

    for cd in companies_data:
        if is_company_suppressed(
            cd.company,
            cd.emails,
            suppressed_emails,
            suppressed_domains,
            suppressed_companies,
        ):
            continue

        # Build contact-email lookup
        contact_emails: dict[object, list[Email]] = {}
        for email in cd.emails:
            if email.contact_id is None:
                continue
            contact_emails.setdefault(email.contact_id, []).append(email)

        # Build phone lookup
        contact_phones: dict[object, list[Phone]] = {}
        for phone in cd.phones:
            if phone.contact_id is None:
                continue
            contact_phones.setdefault(phone.contact_id, []).append(phone)

        # For each contact, pick best exportable email
        contact_best: list[tuple[Contact, Email]] = []
        for contact in cd.contacts:
            emails_for = contact_emails.get(contact.id, [])
            exportable = [
                e for e in emails_for
                if is_exportable_email(e.address, e.status, suppressed_emails, suppressed_domains)
            ]
            if not exportable:
                continue
            # Prefer VALID, then by original order
            exportable.sort(key=lambda e: (0 if e.status == EmailStatus.VALID else 1, e.id))
            contact_best.append((contact, exportable[0]))

        if not contact_best:
            continue

        # Sort: valid email first, then unverified, then by title presence
        def sort_key(pair: tuple[Contact, Email]) -> tuple[int, int]:
            _, em = pair
            c, _ = pair
            status_order = 0 if em.status == EmailStatus.VALID else 1
            has_title = 0 if c.title else 1
            return (status_order, has_title)

        contact_best.sort(key=sort_key)

        score_str = f"{cd.lead.score:.1f}" if cd.lead.score is not None else ""
        score_band_str = cd.lead.score_band.value if cd.lead.score_band is not None else ""

        for contact, best_email in contact_best:
            addr_lower = best_email.address.lower()
            if addr_lower in seen_addresses:
                log.debug(
                    "Skipping duplicate email %s for contact %s in company %s",
                    addr_lower,
                    contact.id,
                    cd.company.id,
                )
                continue
            seen_addresses.add(addr_lower)

            first_name, last_name = _split_name(contact)

            # Best phone for this contact (E.164)
            phones_for = contact_phones.get(contact.id, [])
            phone_str = ""
            if phones_for:
                primary = sorted(phones_for, key=lambda p: (0 if p.is_primary else 1, p.id))
                phone_str = primary[0].number

            rows.append({
                "first_name": first_name,
                "last_name": last_name,
                "email": best_email.address,
                "title": contact.title or "",
                "company_name": cd.company.name,
                "website": cd.company.website or "",
                "city": cd.company.city or "",
                "country": cd.company.country or "",
                "phone": phone_str,
                "score": score_str,
                "score_band": score_band_str,
                "lead_id": str(cd.lead.id),
            })

    return rows


# ---------------------------------------------------------------------------
# Company fallback formatter
# ---------------------------------------------------------------------------


def build_company_fallback_rows(
    companies_data: list[CompanyData],
    suppressed_emails: set[str],
    suppressed_domains: set[str],
    suppressed_companies: set[str],
) -> list[dict]:
    """Build one CSV row per company that has no named-contact export row,
    but does have a usable company-level email or phone.

    A company is eligible when ALL of:
      1. No named contact for this company has an exportable email.
      2. At least one company-level email (contact_id IS NULL) with
         status != INVALID exists, OR at least one company-level phone
         (contact_id IS NULL) exists.
    """
    rows: list[dict] = []

    for cd in companies_data:
        if is_company_suppressed(
            cd.company,
            cd.emails,
            suppressed_emails,
            suppressed_domains,
            suppressed_companies,
        ):
            continue

        # Check condition 1: no named contact has an exportable email
        contact_email_ids = {e.contact_id for e in cd.emails if e.contact_id is not None}
        has_named_exportable = False
        for email in cd.emails:
            if email.contact_id is None:
                continue
            if is_exportable_email(
                email.address, email.status, suppressed_emails, suppressed_domains
            ):
                has_named_exportable = True
                break

        if has_named_exportable:
            continue

        # Company-level emails and phones
        company_emails = [e for e in cd.emails if e.contact_id is None]
        company_phones = [p for p in cd.phones if p.contact_id is None]

        # Check condition 2: at least one usable company-level email or phone
        usable_company_emails = [
            e for e in company_emails if e.status != EmailStatus.INVALID
        ]
        if not usable_company_emails and not company_phones:
            continue

        # Select primary email
        primary_email: Email | None = None
        if usable_company_emails:
            # Sort: is_primary DESC, VALID first, id ASC
            def email_sort_key(e: Email) -> tuple[int, int, object]:
                primary_order = 0 if e.is_primary else 1
                status_order = 0 if e.status == EmailStatus.VALID else 1
                return (primary_order, status_order, e.id)

            usable_company_emails.sort(key=email_sort_key)
            candidate = usable_company_emails[0]
            if is_exportable_email(
                candidate.address, candidate.status, suppressed_emails, suppressed_domains
            ):
                primary_email = candidate

        # Select primary phone
        primary_phone: Phone | None = None
        if company_phones:
            company_phones.sort(key=lambda p: (0 if p.is_primary else 1, p.id))
            primary_phone = company_phones[0]

        # Skip if both are blocked/missing
        if primary_email is None and primary_phone is None:
            continue

        score_str = f"{cd.lead.score:.1f}" if cd.lead.score is not None else ""
        score_band_str = cd.lead.score_band.value if cd.lead.score_band is not None else ""

        rows.append({
            "company_name": cd.company.name,
            "website": cd.company.website or "",
            "email": primary_email.address if primary_email else "",
            "phone": primary_phone.number if primary_phone else "",
            "address": cd.company.address or "",
            "city": cd.company.city or "",
            "country": cd.company.country or "",
            "score": score_str,
            "score_band": score_band_str,
            "lead_id": str(cd.lead.id),
        })

    return rows


# ---------------------------------------------------------------------------
# Full leads formatter (management view)
# ---------------------------------------------------------------------------


def build_full_leads_rows(
    companies_data: list[CompanyData],
    suppressed_emails: set[str],
    suppressed_domains: set[str],
    suppressed_companies: set[str],
) -> list[dict]:
    """Build one CSV row per company — management view; no row exclusion.

    Includes suppressed=True column so suppressions are visible.
    """
    rows: list[dict] = []

    for cd in companies_data:
        suppressed = is_company_suppressed(
            cd.company,
            cd.emails,
            suppressed_emails,
            suppressed_domains,
            suppressed_companies,
        )

        company_emails = [e for e in cd.emails if e.contact_id is None]
        company_phones = [p for p in cd.phones if p.contact_id is None]

        # Best company-level email
        valid_company_emails = [e for e in company_emails if e.status != EmailStatus.INVALID]
        best_email = ""
        if valid_company_emails:
            valid_company_emails.sort(key=lambda e: (0 if e.is_primary else 1, e.id))
            best_email = valid_company_emails[0].address

        # Best company-level phone
        best_phone = ""
        if company_phones:
            company_phones.sort(key=lambda p: (0 if p.is_primary else 1, p.id))
            best_phone = company_phones[0].number

        # Counts
        contact_count = len(cd.contacts)
        exportable_email_count = sum(
            1 for e in cd.emails
            if e.contact_id is not None
            and is_exportable_email(e.address, e.status, suppressed_emails, suppressed_domains)
        )
        company_email_count = sum(
            1 for e in cd.emails
            if e.contact_id is None and e.status != EmailStatus.INVALID
        )

        # Named contacts: top 3 — "Full Name (Title)" or "Full Name"
        def contact_label(c: Contact) -> str:
            name = c.full_name or (
                " ".join(filter(None, [c.first_name, c.last_name]))
            ) or "?"
            return f"{name} ({c.title})" if c.title else name

        named_contacts_str = "; ".join(
            contact_label(c) for c in cd.contacts[:3]
        )

        # Exportable emails across all contacts: top 3
        exportable_addrs: list[str] = []
        for email in cd.emails:
            if email.contact_id is None:
                continue
            if is_exportable_email(email.address, email.status, suppressed_emails, suppressed_domains):
                exportable_addrs.append(email.address)
        exportable_emails_str = "; ".join(exportable_addrs[:3])

        score_str = f"{cd.lead.score:.1f}" if cd.lead.score is not None else ""
        score_band_str = cd.lead.score_band.value if cd.lead.score_band is not None else ""
        review_approved_at_str = ""
        if cd.lead.review_decided_at is not None:
            review_approved_at_str = cd.lead.review_decided_at.isoformat()

        # Website gap signals — read from score_details if available
        _gap_signals = (cd.lead.score_details or {}).get("website_gap_signals") or {}
        website_status = _gap_signals.get("website_status") or ("none" if not cd.company.has_website else "present")
        website_gap_score = (cd.lead.score_details or {}).get("website_gap", "")

        rows.append({
            "company_name": cd.company.name,
            "website": cd.company.website or "",
            "website_status": website_status,
            "website_gap_score": website_gap_score,
            "email": best_email,
            "phone": best_phone,
            "address": cd.company.address or "",
            "city": cd.company.city or "",
            "country": cd.company.country or "",
            "score": score_str,
            "score_band": score_band_str,
            "contact_count": contact_count,
            "exportable_email_count": exportable_email_count,
            "company_email_count": company_email_count,
            "named_contacts": named_contacts_str,
            "exportable_emails": exportable_emails_str,
            "review_approved_at": review_approved_at_str,
            "lead_id": str(cd.lead.id),
            "suppressed": suppressed,
        })

    return rows
