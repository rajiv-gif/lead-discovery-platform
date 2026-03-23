"""Review queue routes.

Uses lower-level action functions from ``src/review/actions.py`` rather than
the interactive CLI runner.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from fastapi.responses import HTMLResponse, Response

from src.dashboard.deps import templates
from src.db.session import get_session
from src.models.campaign import Campaign
from src.models.company_lead import CompanyLead
from src.models.contact import Contact
from src.models.email import Email
from src.models.enums import ReviewStatus, ScoreBand
from src.models.phone import Phone
from src.review.actions import approve_lead, mark_needs_edit, reject_lead

router = APIRouter()

_DEFAULT_MIN_SCORE = 25.0


def _load_lead_data(session, lead: CompanyLead) -> dict:
    """Return display data dict for a single lead card."""
    company = lead.company
    contacts = session.execute(
        select(Contact).where(Contact.company_id == company.id)
    ).scalars().all()
    emails = session.execute(
        select(Email).where(Email.company_id == company.id)
    ).scalars().all()
    phones = session.execute(
        select(Phone).where(Phone.company_id == company.id)
    ).scalars().all()

    contact_emails = {e.contact_id: e for e in emails if e.contact_id is not None}
    company_emails = [e for e in emails if e.contact_id is None]
    company_phones = [p for p in phones if p.contact_id is None]

    return {
        "lead": lead,
        "company": company,
        "contacts": list(contacts),
        "contact_emails": contact_emails,
        "company_emails": company_emails,
        "company_phones": company_phones,
    }


@router.get("/campaigns/{campaign_id}/review", response_class=HTMLResponse)
async def review_queue(
    request: Request,
    campaign_id: uuid.UUID,
    min_score: float = _DEFAULT_MIN_SCORE,
) -> HTMLResponse:
    with get_session() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            return HTMLResponse("Campaign not found", status_code=404)

        leads = session.execute(
            select(CompanyLead)
            .options(joinedload(CompanyLead.company))
            .where(
                CompanyLead.campaign_id == campaign_id,
                CompanyLead.review_status == ReviewStatus.PENDING,
                CompanyLead.score >= min_score,
            )
            .order_by(CompanyLead.score.desc())
        ).scalars().all()

        lead_data = [_load_lead_data(session, lead) for lead in leads]

    return templates.TemplateResponse(
        request,
        "review/queue.html",
        {
            "campaign": campaign,
            "lead_data": lead_data,
            "min_score": min_score,
        },
    )


# ---------------------------------------------------------------------------
# Per-lead action endpoints — return a replacement card fragment
# ---------------------------------------------------------------------------


def _reviewed_card(lead_id: uuid.UUID, action: str) -> HTMLResponse:
    """Return a minimal replacement fragment after a review action."""
    labels = {
        "approve": ("✓ Approved", "approved"),
        "reject": ("✗ Rejected", "rejected"),
        "needs-edit": ("✎ Needs edit", "needs-edit"),
    }
    label, css_class = labels.get(action, ("Done", "done"))
    html = (
        f'<article id="lead-{lead_id}" class="lead-card lead-card--{css_class}" '
        f'aria-hidden="true" style="opacity:0.4">'
        f"<p><em>{label}</em></p>"
        f"</article>"
    )
    return HTMLResponse(html)


@router.post(
    "/campaigns/{campaign_id}/review/{lead_id}/approve",
    response_class=HTMLResponse,
)
async def review_approve(
    campaign_id: uuid.UUID, lead_id: uuid.UUID
) -> HTMLResponse:
    with get_session() as session:
        approve_lead(session, lead_id)
        session.commit()
    return _reviewed_card(lead_id, "approve")


@router.post(
    "/campaigns/{campaign_id}/review/{lead_id}/reject",
    response_class=HTMLResponse,
)
async def review_reject(
    campaign_id: uuid.UUID, lead_id: uuid.UUID
) -> HTMLResponse:
    with get_session() as session:
        reject_lead(session, lead_id)
        session.commit()
    return _reviewed_card(lead_id, "reject")


@router.post(
    "/campaigns/{campaign_id}/review/{lead_id}/needs-edit",
    response_class=HTMLResponse,
)
async def review_needs_edit(
    campaign_id: uuid.UUID, lead_id: uuid.UUID
) -> HTMLResponse:
    with get_session() as session:
        mark_needs_edit(session, lead_id)
        session.commit()
    return _reviewed_card(lead_id, "needs-edit")


# ---------------------------------------------------------------------------
# Bulk action endpoints
# ---------------------------------------------------------------------------


def _refresh_response() -> Response:
    """Tell HTMX to do a full page reload after a bulk action."""
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/campaigns/{campaign_id}/review/bulk/approve-all")
async def bulk_approve_all(
    campaign_id: uuid.UUID,
    min_score: float = Query(default=_DEFAULT_MIN_SCORE),
) -> Response:
    """Approve every pending lead visible at the current min_score filter."""
    with get_session() as session:
        leads = session.execute(
            select(CompanyLead).where(
                CompanyLead.campaign_id == campaign_id,
                CompanyLead.review_status == ReviewStatus.PENDING,
                CompanyLead.score >= min_score,
            )
        ).scalars().all()
        for lead in leads:
            approve_lead(session, lead.id)
        session.commit()
    return _refresh_response()


@router.post("/campaigns/{campaign_id}/review/bulk/reject-cold")
async def bulk_reject_cold(
    campaign_id: uuid.UUID,
    min_score: float = Query(default=_DEFAULT_MIN_SCORE),
) -> Response:
    """Reject all pending COLD-band leads (score < 50) at the current filter."""
    with get_session() as session:
        leads = session.execute(
            select(CompanyLead).where(
                CompanyLead.campaign_id == campaign_id,
                CompanyLead.review_status == ReviewStatus.PENDING,
                CompanyLead.score >= min_score,
                CompanyLead.score_band == ScoreBand.COLD,
            )
        ).scalars().all()
        for lead in leads:
            reject_lead(session, lead.id)
        session.commit()
    return _refresh_response()
