"""Orchestrate CSV export for a campaign."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from src.config.settings import Settings
from src.db.session import get_session
from src.export.formatters import (
    COMPANY_FALLBACK_FIELDS,
    FULL_LEADS_FIELDS,
    NAMED_CONTACTS_FIELDS,
    CompanyData,
    build_company_fallback_rows,
    build_full_leads_rows,
    build_named_contacts_rows,
    load_suppression_sets,
)
from src.export.writer import write_csv
from src.models.campaign import Campaign
from src.models.company import Company
from src.models.company_lead import CompanyLead
from src.models.contact import Contact
from src.models.email import Email
from src.models.enums import LeadStatus, ReviewStatus
from src.models.phone import Phone

log = logging.getLogger(__name__)


@dataclass
class ExportSummary:
    contacts_file: str = ""
    companies_file: str = ""
    leads_file: str = ""
    contacts_rows: int = 0
    companies_rows: int = 0
    leads_rows: int = 0
    approved_companies: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def record_error(self, detail: str) -> None:
        self.errors += 1
        self.error_details.append(detail)


def run_export_for_campaign(
    campaign_id: uuid.UUID,
    export_dir: Optional[Path] = None,
    only_uncontacted: bool = False,
    include_converted: bool = False,
) -> ExportSummary:
    """Export approved leads for a campaign to three CSV files.

    Files are written to:
        <export_dir>/<campaign_id>/contacts_<YYYYMMDD_HHMMSS>.csv
        <export_dir>/<campaign_id>/companies_<YYYYMMDD_HHMMSS>.csv
        <export_dir>/<campaign_id>/leads_<YYYYMMDD_HHMMSS>.csv

    Args:
        campaign_id: Campaign to export.
        export_dir: Base directory for output. Defaults to settings.export_dir.
        only_uncontacted: If True, exclude CONTACTED (and CONVERTED, CHURNED) leads.
        include_converted: If True, include CONVERTED leads (CHURNED always excluded).

    Returns:
        ExportSummary with file paths and row counts.
    """
    settings = Settings()
    if export_dir is None:
        export_dir = Path(settings.export_dir)

    summary = ExportSummary()

    with get_session() as session:
        # Validate campaign
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        # Build status filter
        excluded_statuses = {LeadStatus.DISQUALIFIED, LeadStatus.CHURNED}
        if only_uncontacted:
            excluded_statuses.add(LeadStatus.CONTACTED)
            excluded_statuses.add(LeadStatus.CONVERTED)
        elif not include_converted:
            excluded_statuses.add(LeadStatus.CONVERTED)

        lead_query = select(CompanyLead).where(
            CompanyLead.campaign_id == campaign_id,
            CompanyLead.review_status == ReviewStatus.APPROVED,
            CompanyLead.status.not_in(list(excluded_statuses)),
        )

        leads = session.execute(lead_query).scalars().all()
        summary.approved_companies = len(leads)

        # Build CompanyData for each lead
        companies_data: list[CompanyData] = []
        for lead in leads:
            try:
                company = session.get(Company, lead.company_id)
                if company is None:
                    summary.record_error(f"Company {lead.company_id} not found for lead {lead.id}")
                    continue

                contacts = session.execute(
                    select(Contact).where(Contact.company_id == lead.company_id)
                ).scalars().all()

                emails = session.execute(
                    select(Email).where(Email.company_id == lead.company_id)
                ).scalars().all()

                phones = session.execute(
                    select(Phone).where(Phone.company_id == lead.company_id)
                ).scalars().all()

                companies_data.append(CompanyData(
                    company=company,
                    lead=lead,
                    contacts=list(contacts),
                    emails=list(emails),
                    phones=list(phones),
                ))
            except Exception as exc:
                summary.record_error(f"lead={lead.id}: {exc}")
                log.error("Error loading data for lead %s: %s", lead.id, exc, exc_info=True)

        # Load suppression sets
        try:
            suppressed_emails, suppressed_domains, suppressed_companies = load_suppression_sets(session)
        except Exception as exc:
            summary.record_error(f"Failed to load suppression sets: {exc}")
            log.error("Failed to load suppression sets: %s", exc, exc_info=True)
            suppressed_emails, suppressed_domains, suppressed_companies = set(), set(), set()

        # Build rows
        try:
            contact_rows = build_named_contacts_rows(
                companies_data, suppressed_emails, suppressed_domains, suppressed_companies
            )
        except Exception as exc:
            summary.record_error(f"Failed to build named contact rows: {exc}")
            log.error("Named contacts formatter error: %s", exc, exc_info=True)
            contact_rows = []

        try:
            company_rows = build_company_fallback_rows(
                companies_data, suppressed_emails, suppressed_domains, suppressed_companies
            )
        except Exception as exc:
            summary.record_error(f"Failed to build company fallback rows: {exc}")
            log.error("Company fallback formatter error: %s", exc, exc_info=True)
            company_rows = []

        try:
            lead_rows = build_full_leads_rows(
                companies_data, suppressed_emails, suppressed_domains, suppressed_companies
            )
        except Exception as exc:
            summary.record_error(f"Failed to build full leads rows: {exc}")
            log.error("Full leads formatter error: %s", exc, exc_info=True)
            lead_rows = []

        # Write CSVs
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = export_dir / str(campaign_id)

        contacts_path = out_dir / f"contacts_{ts}.csv"
        companies_path = out_dir / f"companies_{ts}.csv"
        leads_path = out_dir / f"leads_{ts}.csv"

        try:
            summary.contacts_rows = write_csv(contact_rows, contacts_path, NAMED_CONTACTS_FIELDS)
            summary.contacts_file = str(contacts_path)
        except Exception as exc:
            summary.record_error(f"Failed to write contacts CSV: {exc}")
            log.error("CSV write error (contacts): %s", exc, exc_info=True)

        try:
            summary.companies_rows = write_csv(company_rows, companies_path, COMPANY_FALLBACK_FIELDS)
            summary.companies_file = str(companies_path)
        except Exception as exc:
            summary.record_error(f"Failed to write companies CSV: {exc}")
            log.error("CSV write error (companies): %s", exc, exc_info=True)

        try:
            summary.leads_rows = write_csv(lead_rows, leads_path, FULL_LEADS_FIELDS)
            summary.leads_file = str(leads_path)
        except Exception as exc:
            summary.record_error(f"Failed to write leads CSV: {exc}")
            log.error("CSV write error (leads): %s", exc, exc_info=True)

    return summary
