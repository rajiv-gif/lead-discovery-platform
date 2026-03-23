"""Shared dashboard dependencies: templates, stage counts helper."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.company_lead import CompanyLead
from src.models.discovery_hit import DiscoveryHit
from src.models.email import Email
from src.models.enums import DiscoveryHitStatus, EmailStatus, ReviewStatus

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Per-stage hint strings shown alongside error messages in the UI.
# Kept here so they are easy to update without touching route code.
STAGE_ERROR_HINTS: dict[str, str] = {
    "discover": (
        "Check GOOGLE_PLACES_API_KEY is set and the query returned results. "
        "Try narrowing the niche or city."
    ),
    "scrape": (
        "Check network connectivity and SCRAPER_RATE_LIMIT_DELAY. "
        "Some sites block automated requests — the scraper will skip them and continue."
    ),
    "extract": (
        "Check ANTHROPIC_API_KEY and EXTRACTION_MODEL are correct. "
        "Verify the model name matches an available Claude model."
    ),
    "verify": (
        "Email verification is best-effort — partial failures are normal. "
        "Check logs for repeated DNS errors."
    ),
    "score": (
        "Scoring requires extracted leads. Run the extract stage first, "
        "then re-run score."
    ),
}


def get_stage_counts(session: Session, campaign_id: uuid.UUID) -> dict:
    """Return a dict of stage-level counts for a campaign's detail page.

    All queries use the campaign's discovery_hits as the root, then fan out
    to company-level data via a company_id subquery to avoid cross-join
    duplicates.

    Returns:
        dict with keys:
          total_hits, scraped, extracted, verified_emails, total_leads,
          pending_review, approved
    """
    # --- Company IDs belonging to this campaign ---
    company_ids_sq = (
        select(DiscoveryHit.company_id)
        .where(
            DiscoveryHit.campaign_id == campaign_id,
            DiscoveryHit.company_id.is_not(None),
        )
        .distinct()
        .scalar_subquery()
    )

    # --- Discovery ---
    total_hits = session.scalar(
        select(func.count()).select_from(DiscoveryHit).where(
            DiscoveryHit.campaign_id == campaign_id
        )
    ) or 0

    scraped = session.scalar(
        select(func.count()).select_from(DiscoveryHit).where(
            DiscoveryHit.campaign_id == campaign_id,
            DiscoveryHit.status.in_([
                DiscoveryHitStatus.SCRAPED,
                DiscoveryHitStatus.EXTRACTED,
            ]),
        )
    ) or 0

    extracted = session.scalar(
        select(func.count()).select_from(DiscoveryHit).where(
            DiscoveryHit.campaign_id == campaign_id,
            DiscoveryHit.status == DiscoveryHitStatus.EXTRACTED,
        )
    ) or 0

    # --- Verify: non-UNVERIFIED emails for companies in this campaign ---
    verified_emails = session.scalar(
        select(func.count()).select_from(Email).where(
            Email.company_id.in_(company_ids_sq),
            Email.status != EmailStatus.UNVERIFIED,
        )
    ) or 0

    # --- Score: company_leads for this campaign ---
    total_leads = session.scalar(
        select(func.count()).select_from(CompanyLead).where(
            CompanyLead.campaign_id == campaign_id
        )
    ) or 0

    pending_review = session.scalar(
        select(func.count()).select_from(CompanyLead).where(
            CompanyLead.campaign_id == campaign_id,
            CompanyLead.review_status == ReviewStatus.PENDING,
        )
    ) or 0

    approved = session.scalar(
        select(func.count()).select_from(CompanyLead).where(
            CompanyLead.campaign_id == campaign_id,
            CompanyLead.review_status == ReviewStatus.APPROVED,
        )
    ) or 0

    return {
        "total_hits": total_hits,
        "scraped": scraped,
        "extracted": extracted,
        "verified_emails": verified_emails,
        "total_leads": total_leads,
        "pending_review": pending_review,
        "approved": approved,
    }
