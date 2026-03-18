"""Orchestrate per-hit extraction for a campaign."""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.session import get_session
from src.extraction.deterministic import extract_from_page
from src.extraction.linker import link
from src.extraction.llm import AnthropicClient, LLMClient, call_llm
from src.extraction.merge import merge
from src.extraction.models import ExtractionResult
from src.extraction.persist import persist_result
from src.models.campaign import Campaign
from src.models.company import Company
from src.models.company_page import CompanyPage
from src.models.discovery_hit import DiscoveryHit
from src.models.enums import DiscoveryHitStatus, PageType, PhoneType
from src.models.phone import Phone

log = logging.getLogger(__name__)

# Page types that are eligible for LLM triggering (priority order)
_LLM_CANDIDATE_TYPES = [PageType.TEAM, PageType.CONTACT, PageType.ABOUT]


@dataclass
class ExtractionSummary:
    hits_processed: int = 0         # total hits attempted
    hits_with_data: int = 0         # hits where at least one contact/email/phone written
    hits_zero_data: int = 0         # hits that ran cleanly but found nothing
    hits_failed: int = 0            # hits that raised an unhandled exception
    hits_skipped: int = 0           # hits with no scraped pages
    contacts_created: int = 0
    emails_created: int = 0
    phones_created: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def record_error(self, detail: str) -> None:
        self.errors += 1
        self.error_details.append(detail)


def _select_llm_page(pages: list[CompanyPage]) -> Optional[CompanyPage]:
    """Select the best page for LLM extraction. Priority: team > contact > about, then highest word_count."""
    for pt in _LLM_CANDIDATE_TYPES:
        candidates = [p for p in pages if p.page_type == pt and (p.word_count or 0) >= 30]
        if candidates:
            return max(candidates, key=lambda p: p.word_count or 0)
    return None


def _has_sufficient_signal(page: CompanyPage) -> bool:
    """Return True if the page has at least one email, phone, or capitalised two-word phrase."""
    text = page.extracted_text or ""
    has_email = bool(re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text))
    has_phone = bool(re.search(r"\b[\d\s\(\)\-\+]{7,}\b", text))
    has_name_like = bool(re.search(r"[A-Z][a-z]+\s+[A-Z][a-z]+", text))
    return has_email or has_phone or has_name_like


def _extract_hit(
    session: Session,
    hit: DiscoveryHit,
    llm_client: Optional[LLMClient],
    llm_runs_dir: Path,
    max_tokens: int,
    summary: ExtractionSummary,
) -> None:
    summary.hits_processed += 1

    if hit.company_id is None:
        hit.status = DiscoveryHitStatus.SKIPPED
        summary.hits_skipped += 1
        return

    company = session.get(Company, hit.company_id)
    if company is None:
        hit.status = DiscoveryHitStatus.SKIPPED
        summary.hits_skipped += 1
        return

    pages = session.execute(
        select(CompanyPage).where(CompanyPage.company_id == hit.company_id)
    ).scalars().all()

    if not pages:
        hit.status = DiscoveryHitStatus.SKIPPED
        summary.hits_skipped += 1
        return

    country_hint = company.country or "GB"

    # --- Deterministic extraction (one result per page) ---
    det_results = [extract_from_page(p, country_hint) for p in pages]

    # --- LLM trigger check ---
    llm_result = None
    det_contacts = [c for r in det_results for c in r.contacts]
    if llm_client is not None and len(det_contacts) == 0:
        llm_page = _select_llm_page(list(pages))
        if llm_page and _has_sufficient_signal(llm_page):
            llm_result = call_llm(
                client=llm_client,
                page=llm_page,
                company_name=company.name,
                llm_runs_dir=llm_runs_dir,
                max_tokens=max_tokens,
            )

    # --- Link: merges all per-page results and applies footer/generic logic ---
    linked_det = link(det_results)

    # --- Merge deterministic + LLM, deduplicating ---
    final_result = merge(linked_det, llm_result)

    # --- Persist ---
    ps = persist_result(session, hit.company_id, final_result, country_hint)

    # --- Fallback: seed phone from Google Places if extraction found none ---
    # Many business websites hide phone numbers in images or JS. The Places API
    # always returns a phone number; seed it as an UNKNOWN-type Phone record so
    # the lead is not disqualified for having zero contact channels.
    places_phone_seeded = 0
    if ps.phones_created == 0:
        places_phone = (company.extra_fields or {}).get("phone")
        if places_phone:
            session.add(Phone(
                company_id=hit.company_id,
                number=places_phone,
                raw_number=places_phone,
                phone_type=PhoneType.UNKNOWN,
                is_primary=True,
            ))
            places_phone_seeded = 1
            log.debug(
                "Seeded Places phone %r for company %s (extraction found none)",
                places_phone,
                hit.company_id,
            )

    has_data = (ps.contacts_created + ps.emails_created + ps.phones_created + places_phone_seeded) > 0
    hit.status = DiscoveryHitStatus.EXTRACTED
    hit.error_message = None

    if has_data:
        summary.hits_with_data += 1
    else:
        summary.hits_zero_data += 1

    summary.contacts_created += ps.contacts_created
    summary.emails_created += ps.emails_created
    summary.phones_created += ps.phones_created + places_phone_seeded


def run_extraction_for_campaign(campaign_id: uuid.UUID) -> ExtractionSummary:
    settings = Settings()
    summary = ExtractionSummary()

    llm_client: Optional[LLMClient] = None
    if settings.anthropic_api_key:
        llm_client = AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.extraction_model,
        )

    llm_runs_dir = Path("data/llm_runs")
    llm_runs_dir.mkdir(parents=True, exist_ok=True)

    with get_session() as session:
        # Validate campaign exists
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

        hits = session.execute(
            select(DiscoveryHit).where(
                DiscoveryHit.campaign_id == campaign_id,
                DiscoveryHit.status == DiscoveryHitStatus.SCRAPED,
            )
        ).scalars().all()

        for hit in hits:
            try:
                _extract_hit(
                    session=session,
                    hit=hit,
                    llm_client=llm_client,
                    llm_runs_dir=llm_runs_dir,
                    max_tokens=settings.extraction_max_tokens,
                    summary=summary,
                )
                session.commit()
            except Exception as exc:
                session.rollback()
                hit.status = DiscoveryHitStatus.FAILED
                hit.error_message = str(exc)
                session.commit()
                summary.hits_failed += 1
                summary.record_error(f"hit={hit.id}: {exc}")
                log.error("Extraction failed for hit %s: %s", hit.id, exc, exc_info=True)

    return summary
