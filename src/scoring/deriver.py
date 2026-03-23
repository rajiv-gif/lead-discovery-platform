"""Derive (insert or update) a CompanyLead from scoring results.

Also provides outreach status transition helpers for post-review lifecycle
management: mark_contacted, mark_converted, mark_churned.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.models.company_lead import CompanyLead
from src.models.enums import LeadStatus, ReviewStatus, SuppressionType
from src.models.suppression_list import SuppressionList
from src.scoring.aeo import detect_aeo_signals
from src.scoring.scorer import ScoringResult, compute_score


def check_suppression(session: Session, company) -> bool:
    """Return True if *company* matches any active suppression entry.

    Checks:
    1. DOMAIN — company.domain or domain extracted from any email address
    2. EMAIL  — any email address (contact-level or company-level)
    3. COMPANY — company.name (case-insensitive)
    """
    # Collect all email addresses and domains for this company
    email_addresses: list[str] = []
    domains: set[str] = set()

    if company.domain:
        domains.add(company.domain.lower())

    for email in company.emails:
        addr = email.address.lower()
        email_addresses.append(addr)
        domain_part = addr.split("@", 1)[-1]
        domains.add(domain_part)

    # --- DOMAIN check ---
    if domains:
        domain_rows = (
            session.query(SuppressionList)
            .filter(
                SuppressionList.suppression_type == SuppressionType.DOMAIN,
                SuppressionList.value.in_(list(domains)),
            )
            .first()
        )
        if domain_rows:
            return True

    # --- EMAIL check ---
    if email_addresses:
        email_rows = (
            session.query(SuppressionList)
            .filter(
                SuppressionList.suppression_type == SuppressionType.EMAIL,
                SuppressionList.value.in_(email_addresses),
            )
            .first()
        )
        if email_rows:
            return True

    # --- COMPANY name check (case-insensitive) ---
    if company.name:
        company_row = (
            session.query(SuppressionList)
            .filter(
                SuppressionList.suppression_type == SuppressionType.COMPANY,
            )
            .all()
        )
        company_name_lower = company.name.lower()
        for row in company_row:
            if row.value.lower() == company_name_lower:
                return True

    return False


def derive_company_lead(
    session: Session,
    company,
    contacts: list,
    emails: list,
    phones: list,
    pages: list,
    campaign_id: uuid.UUID,
    website_reachable: bool,
) -> CompanyLead:
    """Create or update the :class:`CompanyLead` for *company*.

    On INSERT: all fields set; status=NEW; review_status=PENDING.
    On UPDATE: only score/score_band/score_details updated.
               review_status and campaign_id are preserved.
               If newly disqualified, status is set to DISQUALIFIED.
    """
    is_suppressed = check_suppression(session, company)
    aeo_signals = detect_aeo_signals(pages)
    scoring_result: ScoringResult = compute_score(
        company=company,
        contacts=contacts,
        emails=emails,
        phones=phones,
        pages=pages,
        website_reachable=website_reachable,
        is_suppressed=is_suppressed,
        aeo_signals=aeo_signals,
    )

    existing: CompanyLead | None = (
        session.query(CompanyLead)
        .filter_by(company_id=company.id)
        .one_or_none()
    )

    if existing is None:
        lead = CompanyLead(
            company_id=company.id,
            campaign_id=campaign_id,
            status=LeadStatus.DISQUALIFIED if scoring_result.is_disqualified else LeadStatus.NEW,
            score=scoring_result.score,
            score_band=scoring_result.score_band,
            score_details=scoring_result.score_details,
            review_status=ReviewStatus.PENDING,
        )
        session.add(lead)
        return lead
    else:
        existing.score = scoring_result.score
        existing.score_band = scoring_result.score_band
        existing.score_details = scoring_result.score_details
        # Escalate status to DISQUALIFIED if now failing hard rules
        if scoring_result.is_disqualified and existing.status != LeadStatus.DISQUALIFIED:
            existing.status = LeadStatus.DISQUALIFIED
        return existing


# ---------------------------------------------------------------------------
# Outreach transition helpers
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, list[str]] = {
    "qualified": ["contacted"],
    "contacted": ["converted", "churned"],
    "converted": ["churned"],
}


def mark_contacted(session: Session, lead_id: uuid.UUID) -> CompanyLead:
    """Transition lead status to CONTACTED and set contacted_at.

    Valid source states: QUALIFIED only.

    Raises:
        ValueError: If lead not found or transition is not valid.
    """
    lead = session.get(CompanyLead, lead_id)
    if lead is None:
        raise ValueError(f"Lead not found: {lead_id}")

    current = lead.status.value
    target = LeadStatus.CONTACTED.value
    allowed = VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise ValueError(
            f"Cannot transition from {current!r} to {target!r}. "
            f"Valid transitions from {current!r}: {allowed}"
        )

    lead.status = LeadStatus.CONTACTED
    lead.contacted_at = datetime.now(tz=timezone.utc)
    session.commit()
    return lead


def mark_converted(session: Session, lead_id: uuid.UUID) -> CompanyLead:
    """Transition lead status to CONVERTED and set converted_at.

    Valid source states: CONTACTED only.

    Raises:
        ValueError: If lead not found or transition is not valid.
    """
    lead = session.get(CompanyLead, lead_id)
    if lead is None:
        raise ValueError(f"Lead not found: {lead_id}")

    current = lead.status.value
    target = LeadStatus.CONVERTED.value
    allowed = VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise ValueError(
            f"Cannot transition from {current!r} to {target!r}. "
            f"Valid transitions from {current!r}: {allowed}"
        )

    lead.status = LeadStatus.CONVERTED
    lead.converted_at = datetime.now(tz=timezone.utc)
    session.commit()
    return lead


def mark_churned(session: Session, lead_id: uuid.UUID) -> CompanyLead:
    """Transition lead status to CHURNED.

    Valid source states: CONTACTED or CONVERTED.

    Raises:
        ValueError: If lead not found or transition is not valid.
    """
    lead = session.get(CompanyLead, lead_id)
    if lead is None:
        raise ValueError(f"Lead not found: {lead_id}")

    current = lead.status.value
    target = LeadStatus.CHURNED.value
    allowed = VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise ValueError(
            f"Cannot transition from {current!r} to {target!r}. "
            f"Valid transitions from {current!r}: {allowed}"
        )

    lead.status = LeadStatus.CHURNED
    session.commit()
    return lead
