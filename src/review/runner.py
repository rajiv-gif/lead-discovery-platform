"""Interactive human review of scored leads."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import select

from src.db.session import get_session
from src.models.campaign import Campaign
from src.models.company_lead import CompanyLead
from src.models.contact import Contact
from src.models.email import Email
from src.models.enums import LeadStatus, ReviewStatus
from src.models.phone import Phone

log = logging.getLogger(__name__)
console = Console()

_PROMPT = "[a]pprove / [r]eject / [e]dit / [s]kip ?"


def run_review_for_campaign(
    campaign_id: uuid.UUID,
    min_score: float = 25.0,
) -> dict:
    """Interactive review loop for scored leads above *min_score*.

    Presents each pending lead via Rich, prompts for a decision, and
    commits per decision. Returns a summary dict with decision counts.
    """
    summary = {
        "reviewed": 0,
        "approved": 0,
        "rejected": 0,
        "needs_edit": 0,
        "skipped": 0,
    }

    with get_session() as session:
        # Validate campaign
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        leads = session.execute(
            select(CompanyLead).where(
                CompanyLead.campaign_id == campaign_id,
                CompanyLead.review_status == ReviewStatus.PENDING,
                CompanyLead.score >= min_score,
            ).order_by(CompanyLead.score.desc())
        ).scalars().all()

        for lead in leads:
            company = lead.company

            # Load related data
            contacts = session.execute(
                select(Contact).where(Contact.company_id == company.id)
            ).scalars().all()
            emails = session.execute(
                select(Email).where(Email.company_id == company.id)
            ).scalars().all()
            phones = session.execute(
                select(Phone).where(Phone.company_id == company.id)
            ).scalars().all()

            # Separate contact-linked vs company-level
            contact_emails = [e for e in emails if e.contact_id is not None]
            company_emails = [e for e in emails if e.contact_id is None]
            contact_phones = [p for p in phones if p.contact_id is not None]
            company_phones = [p for p in phones if p.contact_id is None]

            # --- Build display panel ---
            details = _build_panel(
                lead=lead,
                company=company,
                contacts=list(contacts),
                company_emails=company_emails,
                company_phones=company_phones,
                all_emails=list(emails),
                all_phones=list(phones),
            )
            console.print(details)

            # --- Prompt ---
            try:
                decision = input(f"  {_PROMPT}  ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Review interrupted[/yellow]")
                break

            now = datetime.now(tz=timezone.utc)

            if decision == "a":
                lead.review_status = ReviewStatus.APPROVED
                lead.review_decided_at = now
                summary["approved"] += 1
                summary["reviewed"] += 1
                # Status transition on approval
                if lead.status == LeadStatus.NEW:
                    lead.status = LeadStatus.QUALIFIED
                elif lead.status == LeadStatus.DISQUALIFIED:
                    log.warning(
                        "Lead %s is DISQUALIFIED; approval recorded but status unchanged",
                        lead.id,
                    )
                # QUALIFIED, CONTACTED, CONVERTED, CHURNED: preserve existing status
                try:
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    log.error("Failed to commit approval for lead %s: %s", lead.id, exc)
            elif decision == "r":
                lead.review_status = ReviewStatus.REJECTED
                lead.review_decided_at = now
                lead.status = LeadStatus.DISQUALIFIED
                summary["rejected"] += 1
                summary["reviewed"] += 1
                try:
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    log.error("Failed to commit rejection for lead %s: %s", lead.id, exc)
            elif decision == "e":
                lead.review_status = ReviewStatus.NEEDS_EDIT
                lead.review_decided_at = now
                summary["needs_edit"] += 1
                summary["reviewed"] += 1
                try:
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    log.error("Failed to commit needs_edit for lead %s: %s", lead.id, exc)
            else:
                # 's' or anything else → skip
                summary["skipped"] += 1
                console.print("  [dim]Skipped[/dim]")

            console.print()

    return summary


def _build_panel(
    lead: CompanyLead,
    company,
    contacts: list,
    company_emails: list,
    company_phones: list,
    all_emails: list,
    all_phones: list,
) -> Panel:
    """Build a Rich Panel summarising the lead for review."""
    score_details = lead.score_details or {}

    lines: list[str] = [
        f"[bold]{company.name}[/bold]",
        f"  Score: [bold]{lead.score:.1f}[/bold]  Band: [bold]{lead.score_band}[/bold]",
        f"  Contacts: {len(contacts)}  Emails: {len(all_emails)}  Phones: {len(all_phones)}",
        "",
        "[underline]Score breakdown[/underline]",
        f"  Contact richness:     {score_details.get('contact_richness', 0)}",
        f"  Channel availability: {score_details.get('channel_availability', 0)}",
        f"  Verification quality: {score_details.get('verification_quality', 0)}",
        f"  Scrape quality:       {score_details.get('scrape_quality', 0)}",
        f"  Location:             {score_details.get('location', 0)}",
        f"  Website reachable:    {score_details.get('website_reachable', False)}",
        f"  Total:                {score_details.get('total', lead.score)}",
    ]

    if contacts:
        lines.append("")
        lines.append("[underline]Contacts[/underline]")
        for c in contacts:
            name = c.full_name or f"{c.first_name or ''} {c.last_name or ''}".strip() or "?"
            title = f" — {c.title}" if c.title else ""
            c_emails = [e.address for e in all_emails if e.contact_id == c.id]
            c_phones = [p.number for p in all_phones if p.contact_id == c.id]
            email_str = ", ".join(c_emails) if c_emails else ""
            phone_str = ", ".join(c_phones) if c_phones else ""
            contact_line = f"  {name}{title}"
            if email_str:
                contact_line += f"  ✉ {email_str}"
            if phone_str:
                contact_line += f"  ☎ {phone_str}"
            lines.append(contact_line)

    if company_emails:
        lines.append("")
        lines.append("[underline]Company emails[/underline]")
        for e in company_emails:
            lines.append(f"  {e.address} [{e.status}]")

    if company_phones:
        lines.append("")
        lines.append("[underline]Company phones[/underline]")
        for p in company_phones:
            lines.append(f"  {p.number} [{p.phone_type}]")

    body = "\n".join(lines)
    return Panel(body, title=f"Lead review — ID: {lead.id}", expand=False)
