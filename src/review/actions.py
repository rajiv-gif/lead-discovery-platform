"""Lower-level review state-transition functions for the dashboard.

These are the atomic DB operations extracted from the interactive CLI runner
(``src/review/runner.py``) so the dashboard can call them directly without
going through the TTY-based review loop.

Each function:
- Accepts an open SQLAlchemy session (caller owns commit/rollback).
- Returns the mutated ``CompanyLead`` instance.
- Raises ``ValueError`` if the lead does not exist.
- Logs a warning for no-op transitions (e.g. approving a DISQUALIFIED lead).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.models.company_lead import CompanyLead
from src.models.enums import LeadStatus, ReviewStatus

log = logging.getLogger(__name__)


def _load_lead(session: Session, lead_id: uuid.UUID) -> CompanyLead:
    lead = session.get(CompanyLead, lead_id)
    if lead is None:
        raise ValueError(f"CompanyLead {lead_id} not found")
    return lead


def approve_lead(session: Session, lead_id: uuid.UUID) -> CompanyLead:
    """Approve a lead: set review_status=APPROVED.

    Status transition:
    - NEW → QUALIFIED (normal path)
    - DISQUALIFIED → unchanged, warning logged (score gate overridden by reviewer)
    - QUALIFIED / CONTACTED / CONVERTED / CHURNED → preserved (already progressed)

    Commits are the caller's responsibility.
    """
    lead = _load_lead(session, lead_id)
    now = datetime.now(tz=timezone.utc)

    lead.review_status = ReviewStatus.APPROVED
    lead.review_decided_at = now

    if lead.status == LeadStatus.NEW:
        lead.status = LeadStatus.QUALIFIED
        lead.qualified_at = now
    elif lead.status == LeadStatus.DISQUALIFIED:
        log.warning(
            "Lead %s is DISQUALIFIED; review approval recorded but status unchanged", lead_id
        )
    # QUALIFIED, CONTACTED, CONVERTED, CHURNED: preserve without change

    return lead


def reject_lead(session: Session, lead_id: uuid.UUID) -> CompanyLead:
    """Reject a lead: set review_status=REJECTED and status=DISQUALIFIED.

    Commits are the caller's responsibility.
    """
    lead = _load_lead(session, lead_id)
    now = datetime.now(tz=timezone.utc)

    lead.review_status = ReviewStatus.REJECTED
    lead.review_decided_at = now
    lead.status = LeadStatus.DISQUALIFIED

    return lead


def mark_needs_edit(session: Session, lead_id: uuid.UUID) -> CompanyLead:
    """Flag a lead as needing manual edits before re-review.

    Sets review_status=NEEDS_EDIT. Lead status is preserved; the lead remains
    in a non-final review state and will re-appear in filtered queues.

    Commits are the caller's responsibility.
    """
    lead = _load_lead(session, lead_id)
    now = datetime.now(tz=timezone.utc)

    lead.review_status = ReviewStatus.NEEDS_EDIT
    lead.review_decided_at = now

    return lead
