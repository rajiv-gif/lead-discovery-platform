"""Enrichment runner — SMTP pattern probing + LinkedIn owner lookup for campaign leads.

For each company in the campaign that:
  - has a resolvable website domain, AND
  - does NOT already have a verified business-domain email

…this runner:
  1. Searches DuckDuckGo for the business owner's LinkedIn profile and stores
     a Contact record (source="linkedin") if found.
  2. Generates candidate email addresses from extracted/LinkedIn contact names
     plus common generic prefixes (info@, office@, …) and confirms them via SMTP
     RCPT TO probing (no message is ever sent).

Confirmed addresses are stored as Email records and linked to the company.
Enrichment status is recorded in ``company.extra_fields['enriched_at']`` so
the stage count in the dashboard reflects how many companies were processed.

Safe to re-run: companies that already have a business-domain email are skipped,
and duplicate LinkedIn contacts are detected via ``normalized_name_key``.
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from src.config.settings import settings
from src.db.session import get_session
from src.enrichment.hunter import HunterClient, HunterEmail
from src.enrichment.linkedin_lookup import find_owner
from src.enrichment.smtp_prober import FREE_DOMAINS, probe_domain
from src.models.campaign import Campaign
from src.models.company import Company
from src.models.contact import Contact
from src.models.discovery_hit import DiscoveryHit, DiscoveryHitStatus
from src.models.email import Email
from src.models.enums import EmailStatus

log = logging.getLogger(__name__)


@dataclass
class EnrichmentSummary:
    companies_checked: int = 0
    companies_enriched: int = 0   # ≥1 new address found
    companies_skipped: int = 0   # already have biz email / no domain / free domain
    emails_found: int = 0        # VALID addresses stored
    emails_catch_all: int = 0    # CATCH_ALL addresses stored
    hunter_emails_found: int = 0  # emails found via Hunter.io
    linkedin_contacts_found: int = 0  # new owner contacts saved from LinkedIn
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def record_error(self, detail: str) -> None:
        self.errors += 1
        self.error_details.append(detail)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_name_key(full_name: str) -> str:
    """Lowercase + strip punctuation for dedup of contact names."""
    return re.sub(r"[^a-z0-9\s]", "", full_name.lower()).strip()


def _extract_domain(website: str | None) -> str | None:
    """Return bare domain (no www.) from a URL string, or None."""
    if not website:
        return None
    try:
        url = website if "://" in website else f"https://{website}"
        host = urlparse(url).hostname or ""
        return host.removeprefix("www.") or None
    except Exception:
        return None


def _has_business_email(emails: list[Email]) -> bool:
    """True if the company already has at least one non-free-domain email."""
    for e in emails:
        if e.status == EmailStatus.INVALID:
            continue
        domain = e.address.split("@", 1)[-1].lower() if "@" in e.address else ""
        if domain and domain not in FREE_DOMAINS:
            return True
    return False


def _contact_name_pairs(contacts: list[Contact]) -> list[tuple[str, str]]:
    """Extract (first, last) tuples from Contact records."""
    pairs: list[tuple[str, str]] = []
    for c in contacts:
        first = c.first_name or ""
        last = c.last_name or ""
        if not first and not last and c.full_name:
            parts = c.full_name.split()
            first = parts[0] if parts else ""
            last = parts[-1] if len(parts) > 1 else ""
        if first or last:
            pairs.append((first, last))
    return pairs


# ---------------------------------------------------------------------------
# Per-company enrichment
# ---------------------------------------------------------------------------

def _enrich_company(
    company_id: uuid.UUID,
    summary: EnrichmentSummary,
    smtp_timeout: float,
    dns_timeout: float,
) -> None:
    """LinkedIn owner lookup + SMTP probe for one company."""

    # --- Load company data ---
    with get_session() as session:
        company = session.get(Company, company_id)
        if company is None:
            return

        domain = company.domain or _extract_domain(company.website)
        if not domain or domain in FREE_DOMAINS:
            log.debug("Skipping %s — no usable domain (%s)", company.name, domain)
            summary.companies_skipped += 1
            return

        existing_emails = list(
            session.scalars(select(Email).where(Email.company_id == company_id))
        )
        if _has_business_email(existing_emails):
            log.debug("Skipping %s — already has business-domain email", company.name)
            summary.companies_skipped += 1
            return

        existing_addresses: set[str] = {e.address.lower() for e in existing_emails}

        contacts = list(
            session.scalars(select(Contact).where(Contact.company_id == company_id))
        )
        contact_pairs = _contact_name_pairs(contacts)
        company_name = company.name  # capture before session closes
        city = company.city or ""

    # --- LinkedIn owner lookup (outside DB session — makes HTTP requests) ---
    # Disabled by default. Enable via LINKEDIN_LOOKUP_ENABLED=true in .env.
    owner = None
    if settings.linkedin_lookup_enabled:
        try:
            owner = find_owner(
                company_name=company_name,
                city=city,
                delay=settings.linkedin_lookup_delay,
                city_fallback=settings.linkedin_city_fallback_enabled,
            )
        except Exception as exc:
            log.warning("LinkedIn lookup failed for %s: %s", company_name, exc)

    if owner is not None:
        norm_key = _normalise_name_key(owner.full_name)
        with get_session() as session:
            existing_contact = session.execute(
                select(Contact).where(
                    Contact.company_id == company_id,
                    Contact.normalized_name_key == norm_key,
                )
            ).scalar_one_or_none()

            if existing_contact is None:
                new_contact = Contact(
                    company_id=company_id,
                    full_name=owner.full_name,
                    first_name=owner.first_name,
                    last_name=owner.last_name,
                    title=owner.title,
                    linkedin_url=owner.linkedin_url,
                    source="linkedin",
                    normalized_name_key=norm_key,
                    # Persist confidence so callers can filter by quality later.
                    extra_fields={"linkedin_confidence": owner.confidence},
                )
                session.add(new_contact)
                summary.linkedin_contacts_found += 1
                log.info(
                    "LinkedIn owner saved for %s: %s (%s) [confidence=%s]",
                    company_name, owner.full_name, owner.title, owner.confidence,
                )
            else:
                # Backfill linkedin_url and confidence when not already present.
                if not existing_contact.linkedin_url:
                    existing_contact.linkedin_url = owner.linkedin_url
                ef = dict(existing_contact.extra_fields or {})
                if "linkedin_confidence" not in ef:
                    ef["linkedin_confidence"] = owner.confidence
                    existing_contact.extra_fields = ef

        # Include the LinkedIn owner in SMTP candidate contact_pairs only when
        # confidence meets the configured threshold.
        # - linkedin_smtp_high_confidence_only=true (default): only "high"
        # - linkedin_smtp_high_confidence_only=false: "high" and "medium"
        if owner.first_name or owner.last_name:
            passes_confidence = (
                not settings.linkedin_smtp_high_confidence_only
                or owner.confidence == "high"
            )
            if passes_confidence:
                contact_pairs.append((owner.first_name, owner.last_name))
            else:
                log.debug(
                    "Skipping SMTP probing for LinkedIn contact %s — "
                    "confidence=%s below threshold (LINKEDIN_SMTP_HIGH_CONFIDENCE_ONLY=true)",
                    owner.full_name, owner.confidence,
                )

    # --- Hunter.io email discovery (optional — requires HUNTER_API_KEY) ---
    if settings.hunter_api_key:
        hunter = HunterClient(
            api_key=settings.hunter_api_key,
            min_confidence=settings.hunter_min_confidence,
        )

        # 1. Domain search — finds all emails Hunter knows for this domain
        hunter_emails: list[HunterEmail] = hunter.domain_search(domain, limit=10)

        # 2. Email finder — look up personal emails for any named contacts
        for first, last in contact_pairs:
            if not first and not last:
                continue
            found = hunter.email_finder(domain, first, last)
            if found and found.address not in {e.address for e in hunter_emails}:
                hunter_emails.append(found)

        if hunter_emails:
            with get_session() as session:
                for he in hunter_emails:
                    if he.address in existing_addresses:
                        continue

                    # Create a Contact record for personal emails with a known name
                    contact_id = None
                    if he.email_type == "personal" and (he.first_name or he.last_name):
                        full_name = f"{he.first_name or ''} {he.last_name or ''}".strip()
                        norm_key = _normalise_name_key(full_name)
                        existing_contact = session.execute(
                            select(Contact).where(
                                Contact.company_id == company_id,
                                Contact.normalized_name_key == norm_key,
                            )
                        ).scalar_one_or_none()

                        if existing_contact is None:
                            new_contact = Contact(
                                company_id=company_id,
                                full_name=full_name,
                                first_name=he.first_name,
                                last_name=he.last_name,
                                title=he.position,
                                linkedin_url=he.linkedin_url,
                                source="hunter",
                                normalized_name_key=norm_key,
                                extra_fields={"hunter_confidence": he.confidence},
                            )
                            session.add(new_contact)
                            contact_id = None   # will be set after flush if needed
                        else:
                            contact_id = existing_contact.id

                    email = Email(
                        company_id=company_id,
                        contact_id=contact_id,
                        address=he.address,
                        status=EmailStatus.VALID,
                        is_primary=False,
                        mx_valid=True,
                        verified_at=datetime.now(timezone.utc),
                    )
                    session.add(email)
                    existing_addresses.add(he.address)
                    summary.hunter_emails_found += 1
                    log.info(
                        "Hunter [%s, conf=%d] %s → %s",
                        he.email_type, he.confidence, company_name, he.address,
                    )

                if summary.hunter_emails_found > 0:
                    company_obj = session.get(Company, company_id)
                    if company_obj is not None:
                        ef = dict(company_obj.extra_fields or {})
                        ef["hunter_enriched_at"] = datetime.now(timezone.utc).isoformat()
                        ef["hunter_emails_found"] = summary.hunter_emails_found
                        company_obj.extra_fields = ef

    # --- SMTP probe (outside DB session — can be slow) ---
    summary.companies_checked += 1
    log.info("Probing %s for %s", domain, company_name)

    results = probe_domain(
        domain=domain,
        contacts=contact_pairs,
        smtp_timeout=smtp_timeout,
        dns_timeout=dns_timeout,
    )

    if not results:
        # Port 25 blocked or no MX — mark as checked so we don't retry endlessly
        with get_session() as session:
            company = session.get(Company, company_id)
            if company is not None:
                ef = dict(company.extra_fields or {})
                ef["enriched_at"] = datetime.now(timezone.utc).isoformat()
                ef["enriched_emails_found"] = 0
                company.extra_fields = ef
        return

    # --- Persist new emails ---
    new_valid = 0
    new_catch_all = 0

    with get_session() as session:
        for result in results:
            if result.address.lower() in existing_addresses:
                continue
            email = Email(
                company_id=company_id,
                contact_id=None,
                address=result.address,
                status=result.status,
                is_primary=False,
                mx_valid=True,
                verified_at=datetime.now(timezone.utc),
            )
            session.add(email)
            existing_addresses.add(result.address.lower())
            if result.status == EmailStatus.VALID:
                new_valid += 1
            elif result.status == EmailStatus.CATCH_ALL:
                new_catch_all += 1
            log.info(
                "Enriched email [%s] %s → %s",
                result.status.value, company_name, result.address,
            )

        # Record enrichment on the company
        company = session.get(Company, company_id)
        if company is not None:
            ef = dict(company.extra_fields or {})
            ef["enriched_at"] = datetime.now(timezone.utc).isoformat()
            ef["enriched_emails_found"] = new_valid + new_catch_all
            company.extra_fields = ef

    if new_valid + new_catch_all > 0:
        summary.companies_enriched += 1
    summary.emails_found += new_valid
    summary.emails_catch_all += new_catch_all


# ---------------------------------------------------------------------------
# Campaign-level runner
# ---------------------------------------------------------------------------

def run_enrichment_for_campaign(
    campaign_id: uuid.UUID,
    smtp_timeout: float = 10.0,
    dns_timeout: float = 5.0,
    stop_event: threading.Event | None = None,
) -> EnrichmentSummary:
    """Run email enrichment for all companies in *campaign_id*.

    Processes only companies reached by the extract or scrape stages.
    Skips companies that already have a business-domain email.
    """
    summary = EnrichmentSummary()

    with get_session() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        company_ids: list[uuid.UUID] = list(
            session.scalars(
                select(DiscoveryHit.company_id)
                .where(
                    DiscoveryHit.campaign_id == campaign_id,
                    DiscoveryHit.status.in_([
                        DiscoveryHitStatus.EXTRACTED,
                        DiscoveryHitStatus.SCRAPED,
                    ]),
                    DiscoveryHit.company_id.isnot(None),
                )
                .distinct()
            )
        )

    for company_id in company_ids:
        if stop_event is not None and stop_event.is_set():
            log.info("enrich: stop requested — halting")
            break

        try:
            _enrich_company(
                company_id=company_id,
                summary=summary,
                smtp_timeout=smtp_timeout,
                dns_timeout=dns_timeout,
            )
        except Exception as exc:
            log.exception("Enrichment error for company %s", company_id)
            summary.record_error(f"{company_id}: {exc}")

    log.info(
        "Enrichment complete — checked=%d enriched=%d emails=%d catch_all=%d "
        "hunter=%d linkedin=%d skipped=%d errors=%d",
        summary.companies_checked,
        summary.companies_enriched,
        summary.emails_found,
        summary.emails_catch_all,
        summary.hunter_emails_found,
        summary.linkedin_contacts_found,
        summary.companies_skipped,
        summary.errors,
    )
    return summary
