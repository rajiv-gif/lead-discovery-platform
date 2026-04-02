"""Orchestrate scoring for all extracted companies in a campaign."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from src.db.session import get_session
from src.models.campaign import Campaign
from src.models.company import Company
from src.models.company_lead import CompanyLead
from src.models.company_page import CompanyPage
from src.models.contact import Contact
from src.models.discovery_hit import DiscoveryHit
from src.models.email import Email
from src.models.enums import DiscoveryHitStatus, DiscoverySource, LeadStatus, ScoreBand
from src.models.phone import Phone
from src.scoring.deriver import derive_company_lead

log = logging.getLogger(__name__)


@dataclass
class ScoringRunSummary:
    companies_processed: int = 0
    leads_created: int = 0
    leads_updated: int = 0
    leads_disqualified: int = 0
    hot: int = 0
    warm: int = 0
    cold: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def record_error(self, detail: str) -> None:
        self.errors += 1
        self.error_details.append(detail)


def run_scoring_for_campaign(
    campaign_id: uuid.UUID,
    website_results: dict[uuid.UUID, bool] | None = None,
) -> ScoringRunSummary:
    """Score all companies with EXTRACTED discovery hits for a campaign.

    *website_results* maps ``company_id → bool``; if None, all websites are
    treated as unreachable (False).
    """
    if website_results is None:
        website_results = {}

    summary = ScoringRunSummary()

    with get_session() as session:
        # Validate campaign exists
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        # Collect unique company_ids from EXTRACTED hits
        hit_rows = session.execute(
            select(DiscoveryHit.company_id).where(
                DiscoveryHit.campaign_id == campaign_id,
                DiscoveryHit.status == DiscoveryHitStatus.EXTRACTED,
                DiscoveryHit.company_id.is_not(None),
            ).distinct()
        ).scalars().all()

        company_ids = list(set(cid for cid in hit_rows if cid is not None))

        # Web-search campaigns: don't disqualify stores that lack email/phone —
        # DTC/ecommerce brands often use contact forms instead of publishing them.
        require_contact = campaign.discovery_source != DiscoverySource.WEB_SEARCH

        for company_id in company_ids:
            try:
                company = session.get(Company, company_id)
                if company is None:
                    summary.record_error(f"Company {company_id} not found")
                    continue

                contacts = session.execute(
                    select(Contact).where(Contact.company_id == company_id)
                ).scalars().all()

                emails = session.execute(
                    select(Email).where(Email.company_id == company_id)
                ).scalars().all()

                phones = session.execute(
                    select(Phone).where(Phone.company_id == company_id)
                ).scalars().all()

                pages = session.execute(
                    select(CompanyPage).where(CompanyPage.company_id == company_id)
                ).scalars().all()

                website_reachable = website_results.get(company_id, False)

                # Check if this lead already exists
                existing = (
                    session.query(CompanyLead)
                    .filter_by(company_id=company_id)
                    .one_or_none()
                )
                is_new = existing is None

                lead = derive_company_lead(
                    session=session,
                    company=company,
                    contacts=list(contacts),
                    emails=list(emails),
                    phones=list(phones),
                    pages=list(pages),
                    campaign_id=campaign_id,
                    website_reachable=website_reachable,
                    require_contact=require_contact,
                )

                session.flush()  # Assign ID if new

                summary.companies_processed += 1

                if is_new:
                    summary.leads_created += 1
                else:
                    summary.leads_updated += 1

                if lead.status == LeadStatus.DISQUALIFIED:
                    summary.leads_disqualified += 1
                elif lead.score_band == ScoreBand.HOT:
                    summary.hot += 1
                elif lead.score_band == ScoreBand.WARM:
                    summary.warm += 1
                elif lead.score_band == ScoreBand.COLD:
                    summary.cold += 1

                session.commit()

            except Exception as exc:
                session.rollback()
                summary.record_error(f"company={company_id}: {exc}")
                log.error(
                    "Scoring failed for company %s: %s", company_id, exc, exc_info=True
                )

    return summary
