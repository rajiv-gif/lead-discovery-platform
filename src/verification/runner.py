"""Orchestrate per-company verification for a campaign."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from src.db.session import get_session
from src.models.campaign import Campaign
from src.models.company import Company
from src.models.discovery_hit import DiscoveryHit
from src.models.email import Email
from src.models.enums import DiscoveryHitStatus, EmailStatus, PhoneType
from src.models.phone import Phone
from src.verification.email_verifier import verify_email
from src.verification.phone_classifier import classify_phone
from src.verification.website_checker import check_website

log = logging.getLogger(__name__)


@dataclass
class VerificationSummary:
    emails_verified: int = 0
    emails_valid: int = 0
    emails_invalid: int = 0
    emails_risky: int = 0
    phones_classified: int = 0
    websites_checked: int = 0
    websites_reachable: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def record_error(self, detail: str) -> None:
        self.errors += 1
        self.error_details.append(detail)


def run_verification_for_campaign(
    campaign_id: uuid.UUID,
    dns_timeout: float = 5.0,
    http_timeout: float = 10.0,
) -> tuple[VerificationSummary, dict[uuid.UUID, bool]]:
    """Verify all emails, phones, and websites for companies in a campaign.

    Returns ``(summary, website_results)`` where ``website_results`` maps
    ``company_id`` → ``bool`` (True = website reachable).
    """
    summary = VerificationSummary()
    website_results: dict[uuid.UUID, bool] = {}

    with get_session() as session:
        # Validate campaign exists
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        hits = session.execute(
            select(DiscoveryHit).where(
                DiscoveryHit.campaign_id == campaign_id,
                DiscoveryHit.status.in_([
                    DiscoveryHitStatus.EXTRACTED,
                    DiscoveryHitStatus.SCRAPED,
                ]),
            )
        ).scalars().all()

        # Deduplicate companies across hits
        seen_company_ids: set[uuid.UUID] = set()
        for hit in hits:
            if hit.company_id is None or hit.company_id in seen_company_ids:
                continue
            seen_company_ids.add(hit.company_id)

            try:
                company = session.get(Company, hit.company_id)
                if company is None:
                    summary.record_error(f"Company {hit.company_id} not found (hit={hit.id})")
                    continue

                country_hint = company.country or "GB"

                # --- Verify emails ---
                unverified_emails = session.execute(
                    select(Email).where(
                        Email.company_id == hit.company_id,
                        Email.status == EmailStatus.UNVERIFIED,
                    )
                ).scalars().all()

                for email in unverified_emails:
                    try:
                        status, mx_valid = verify_email(email.address, dns_timeout=dns_timeout)
                        email.status = status
                        email.mx_valid = mx_valid
                        email.verified_at = datetime.now(tz=timezone.utc)
                        summary.emails_verified += 1
                        if status == EmailStatus.VALID:
                            summary.emails_valid += 1
                        elif status == EmailStatus.INVALID:
                            summary.emails_invalid += 1
                        elif status == EmailStatus.RISKY:
                            summary.emails_risky += 1
                    except Exception as exc:
                        summary.record_error(
                            f"Email verification failed for {email.address}: {exc}"
                        )
                        log.error("Email verification error for %s: %s", email.address, exc)

                # --- Classify phones ---
                unknown_phones = session.execute(
                    select(Phone).where(
                        Phone.company_id == hit.company_id,
                        Phone.phone_type == PhoneType.UNKNOWN,
                    )
                ).scalars().all()

                for phone in unknown_phones:
                    try:
                        raw = phone.raw_number or phone.number
                        phone_type = classify_phone(raw, country_hint)
                        phone.phone_type = phone_type
                        summary.phones_classified += 1
                    except Exception as exc:
                        summary.record_error(
                            f"Phone classification failed for {phone.number}: {exc}"
                        )
                        log.error("Phone classification error for %s: %s", phone.number, exc)

                # --- Check website ---
                if company.website:
                    try:
                        reachable = check_website(company.website, timeout=http_timeout)
                        website_results[company.id] = reachable
                        summary.websites_checked += 1
                        if reachable:
                            summary.websites_reachable += 1
                    except Exception as exc:
                        summary.record_error(
                            f"Website check failed for {company.website}: {exc}"
                        )
                        log.error("Website check error for %s: %s", company.website, exc)

                session.commit()

            except Exception as exc:
                session.rollback()
                summary.record_error(f"company={hit.company_id}: {exc}")
                log.error(
                    "Verification failed for company %s: %s",
                    hit.company_id, exc, exc_info=True
                )

    return summary, website_results
