"""Pure scoring function — no DB calls, no network."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.models.enums import EmailStatus, PageType, PhoneType, ScoreBand
from src.scoring.aeo import AeoSignals


@dataclass
class ScoringResult:
    score: float
    score_band: ScoreBand
    score_details: dict
    is_disqualified: bool
    disqualification_reason: Optional[str] = None


def compute_score(
    company,
    contacts: list,
    emails: list,
    phones: list,
    pages: list,
    website_reachable: bool,
    is_suppressed: bool,
    aeo_signals: AeoSignals | None = None,
) -> ScoringResult:
    """Compute a quality score for a company/lead.

    This is a pure function — takes ORM objects but makes no DB calls or
    network requests.

    Hard disqualifications (score=0, band=DISQUALIFIED):
    1. company.name is None or empty
    2. No emails AND no phones
    3. is_suppressed is True

    Returns a :class:`ScoringResult` with per-dimension breakdown.
    """
    # --- Hard disqualification checks ---
    if not company.name or not company.name.strip():
        return ScoringResult(
            score=0.0,
            score_band=ScoreBand.DISQUALIFIED,
            score_details={"total": 0},
            is_disqualified=True,
            disqualification_reason="company name is missing",
        )

    if not emails and not phones:
        return ScoringResult(
            score=0.0,
            score_band=ScoreBand.DISQUALIFIED,
            score_details={"total": 0},
            is_disqualified=True,
            disqualification_reason="no emails and no phones",
        )

    if is_suppressed:
        return ScoringResult(
            score=0.0,
            score_band=ScoreBand.DISQUALIFIED,
            score_details={"total": 0},
            is_disqualified=True,
            disqualification_reason="company is suppressed",
        )

    # --- Dimension A: Contact Richness (max 30) ---
    dim_a = 0
    # ≥1 Contact with full_name
    if any(c.full_name for c in contacts):
        dim_a += 12
        # ≥1 Contact with full_name AND title
        if any(c.full_name and c.title for c in contacts):
            dim_a += 8
    # ≥1 Email linked to a contact
    if any(e.contact_id is not None for e in emails):
        dim_a += 6
    # ≥1 Phone linked to a contact
    if any(p.contact_id is not None for p in phones):
        dim_a += 4

    # --- Dimension B: Contact Channel Availability (max 25) ---
    dim_b = 0
    # ≥1 company-level email (contact_id IS NULL)
    if any(e.contact_id is None for e in emails):
        dim_b += 10
    # ≥1 company-level phone (contact_id IS NULL)
    if any(p.contact_id is None for p in phones):
        dim_b += 8
    # company.website is set
    if company.website:
        dim_b += 7

    # --- Dimension C: Verification Quality (max 25) ---
    dim_c = 0
    if any(e.status == EmailStatus.VALID for e in emails):
        dim_c += 10
    if any(e.mx_valid for e in emails):
        dim_c += 5
    if any(p.phone_type != PhoneType.UNKNOWN for p in phones):
        dim_c += 5
    if website_reachable:
        dim_c += 5

    # --- Dimension D: Scrape Quality (max 12) ---
    dim_d = 0
    if pages:
        dim_d += 5
        team_page_types = {PageType.TEAM, PageType.CONTACT, PageType.ABOUT}
        if any(p.page_type in team_page_types for p in pages):
            dim_d += 4
        if any((p.word_count or 0) >= 50 for p in pages):
            dim_d += 3

    # --- Dimension E: Location Data (max 8) ---
    dim_e = 0
    if company.address or company.city:
        dim_e += 5
    if company.country:
        dim_e += 3

    # --- Dimension F: AEO Opportunity (max 15) ---
    # Higher score = more gaps in site optimisation = stronger sales prospect
    # for AEO / AI-search services.
    #   +6  no JSON-LD at all (completely unstructured site)
    #   +3  has JSON-LD but missing LocalBusiness/Dentist schema type
    #   +4  no mobile viewport meta tag
    #   +3  no Open Graph tags
    #   +2  serving over HTTP (not HTTPS)
    dim_f = 0
    if aeo_signals is not None:
        if not aeo_signals.has_json_ld:
            dim_f += 6
        elif not aeo_signals.has_local_business_schema:
            dim_f += 3
        if not aeo_signals.has_viewport_meta:
            dim_f += 4
        if not aeo_signals.has_og_tags:
            dim_f += 3
        if not aeo_signals.is_https:
            dim_f += 2

    total = dim_a + dim_b + dim_c + dim_d + dim_e + dim_f

    # --- Score band ---
    if total >= 75:
        band = ScoreBand.HOT
    elif total >= 50:
        band = ScoreBand.WARM
    else:
        band = ScoreBand.COLD

    score_details = {
        "contact_richness": dim_a,
        "channel_availability": dim_b,
        "verification_quality": dim_c,
        "scrape_quality": dim_d,
        "location": dim_e,
        "aeo_opportunity": dim_f,
        "website_reachable": website_reachable,
        "aeo_signals": {
            "has_json_ld": aeo_signals.has_json_ld if aeo_signals else None,
            "has_local_business_schema": aeo_signals.has_local_business_schema if aeo_signals else None,
            "has_viewport_meta": aeo_signals.has_viewport_meta if aeo_signals else None,
            "has_og_tags": aeo_signals.has_og_tags if aeo_signals else None,
            "is_https": aeo_signals.is_https if aeo_signals else None,
        },
        "total": total,
    }

    return ScoringResult(
        score=float(total),
        score_band=band,
        score_details=score_details,
        is_disqualified=False,
    )
