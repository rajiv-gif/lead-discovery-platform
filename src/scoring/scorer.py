"""Pure scoring function — no DB calls, no network."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.models.enums import CampaignGoal, EmailStatus, PageType, PhoneType, ScoreBand
from src.scoring.aeo import AeoSignals
from src.scoring.tech_signals import TechSignals
from src.scoring.website_gap import WebsiteGapSignals


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
    tech_signals: TechSignals | None = None,
    website_gap: WebsiteGapSignals | None = None,
    campaign_goal: CampaignGoal = CampaignGoal.LEAD_GEN,
    require_contact: bool = True,
) -> ScoringResult:
    """Compute a quality score for a company/lead.

    This is a pure function — takes ORM objects but makes no DB calls or
    network requests.

    Hard disqualifications (score=0, band=DISQUALIFIED):
    1. company.name is None or empty
    2. No emails AND no phones  (skipped when require_contact=False, e.g. web-search campaigns)
    3. is_suppressed is True

    ``require_contact=False`` is used for WEB_SEARCH campaigns where DTC/ecommerce
    brands commonly use contact forms rather than exposing email or phone publicly.

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

    # WEB_AGENCY campaigns: the *absence* of a website is itself the lead signal,
    # so we never disqualify for missing contact data. Contact info from Places
    # (phone, address) is sufficient for a cold-outreach pitch.
    effective_require_contact = require_contact and campaign_goal != CampaignGoal.WEB_AGENCY
    if effective_require_contact and not emails and not phones:
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

    # --- Dimension G: Tech Gap Opportunity (max 10) ---
    # Higher score = more marketing tech gaps = stronger prospect for digital agencies.
    # Each gap is a potential service to pitch (ads, analytics, chat, etc.).
    #   +4  not running any paid ads (no Google Ads, Meta Pixel, or TikTok Pixel)
    #   +2  no Google Analytics (flying blind on traffic)
    #   +2  no live chat widget (visitor engagement gap)
    #   +1  no blog/content section (content marketing gap)
    #   +1  no cookie banner despite EU traffic (compliance gap)
    dim_g = 0
    if tech_signals is not None:
        if not tech_signals.running_paid_ads:
            dim_g += 4
        if tech_signals.missing_analytics:
            dim_g += 2
        if not tech_signals.has_chat:
            dim_g += 2
        if not tech_signals.has_blog:
            dim_g += 1
        if not tech_signals.has_cookie_banner:
            dim_g += 1

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

    # --- Dimension H: Website Gap Opportunity (max 30, WEB_AGENCY only) ---
    # Higher score = bigger website gap = stronger prospect for a web/AI-site agency.
    #   +30  no website at all (immediately actionable pitch)
    #   +8   has website but not HTTPS (looks untrustworthy / outdated)
    #   +7   no mobile viewport (site not mobile-friendly)
    #   +7   copyright year ≥ 3 years old (visibly dated)
    #   +5   no social media links (isolated online presence)
    #   +3   thin content < 100 words (placeholder or abandoned site)
    dim_h = 0
    if campaign_goal == CampaignGoal.WEB_AGENCY and website_gap is not None:
        if not website_gap.has_website:
            dim_h += 30
        else:
            if not website_gap.is_https:
                dim_h += 8
            if not website_gap.has_viewport:
                dim_h += 7
            if website_gap.copyright_year_age >= 3:
                dim_h += 7
            if not website_gap.has_social_links:
                dim_h += 5
            if website_gap.word_count < 100:
                dim_h += 3

    total = dim_a + dim_b + dim_c + dim_d + dim_e + dim_f + dim_g + dim_h

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
        "tech_gap": dim_g,
        "tech_signals": tech_signals.as_dict() if tech_signals else None,
        "aeo_opportunity": dim_f,
        "website_reachable": website_reachable,
        "aeo_signals": {
            "has_json_ld": aeo_signals.has_json_ld if aeo_signals else None,
            "has_local_business_schema": aeo_signals.has_local_business_schema if aeo_signals else None,
            "has_viewport_meta": aeo_signals.has_viewport_meta if aeo_signals else None,
            "has_og_tags": aeo_signals.has_og_tags if aeo_signals else None,
            "is_https": aeo_signals.is_https if aeo_signals else None,
        },
        "website_gap": dim_h,
        "website_gap_signals": {
            "has_website": website_gap.has_website if website_gap else None,
            "is_https": website_gap.is_https if website_gap else None,
            "has_viewport": website_gap.has_viewport if website_gap else None,
            "copyright_year_age": website_gap.copyright_year_age if website_gap else None,
            "has_social_links": website_gap.has_social_links if website_gap else None,
            "word_count": website_gap.word_count if website_gap else None,
            "website_status": website_gap.website_status if website_gap else None,
        } if website_gap else None,
        "total": total,
    }

    return ScoringResult(
        score=float(total),
        score_band=band,
        score_details=score_details,
        is_disqualified=False,
    )
