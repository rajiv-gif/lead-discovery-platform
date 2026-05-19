"""Campaign detail page route."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fastapi.responses import RedirectResponse

from sqlalchemy import select

from src.dashboard.deps import STAGE_ERROR_HINTS, get_stage_counts, templates
from src.dashboard.persistence import get_last_run
from src.dashboard.tasks import registry
from src.db.session import get_session
from src.models.campaign import Campaign
from src.models.company_lead import CompanyLead
from src.models.company_page import CompanyPage
from src.models.discovery_hit import DiscoveryHit
from src.models.pipeline_run import PipelineRun

router = APIRouter()

# Ordered list of pipeline stages shown in the detail page table.
PIPELINE_STAGES = [
    ("discover", "Discovery"),
    ("scrape", "Scrape"),
    ("extract", "Extract"),
    ("enrich", "Enrich"),
    ("verify", "Verify"),
    ("score", "Score"),
]


def _build_stage_rows(counts: dict) -> list[dict]:
    """Map DB counts to per-row display data for the stage table."""
    return [
        {
            "key": "discover",
            "label": "Discovery",
            "count": counts["total_hits"],
            "detail": f"{counts['total_hits']} hits found",
        },
        {
            "key": "scrape",
            "label": "Scrape",
            "count": counts["scraped"],
            "detail": f"{counts['scraped']} of {counts['total_hits']} scraped",
        },
        {
            "key": "extract",
            "label": "Extract",
            "count": counts["extracted"],
            "detail": f"{counts['extracted']} extracted",
        },
        {
            "key": "enrich",
            "label": "Enrich",
            "count": counts["enriched"],
            "detail": f"{counts['enriched']} companies enriched",
        },
        {
            "key": "verify",
            "label": "Verify",
            "count": counts["verified_emails"],
            "detail": f"{counts['verified_emails']} emails verified",
        },
        {
            "key": "score",
            "label": "Score",
            "count": counts["total_leads"],
            "detail": (
                f"{counts['total_leads']} scored, "
                f"{counts['pending_review']} pending review"
            ),
        },
    ]


@router.post("/campaigns/{campaign_id}/delete")
async def campaign_delete(campaign_id: uuid.UUID):
    with get_session() as session:
        # CompanyPage has a FK → discovery_hits.id, so it must be deleted first.
        hit_ids = session.scalars(
            select(DiscoveryHit.id).where(DiscoveryHit.campaign_id == campaign_id)
        ).all()
        if hit_ids:
            session.query(CompanyPage).filter(
                CompanyPage.discovery_hit_id.in_(hit_ids)
            ).delete(synchronize_session=False)
        session.query(PipelineRun).filter_by(campaign_id=campaign_id).delete()
        session.query(CompanyLead).filter_by(campaign_id=campaign_id).delete()
        session.query(DiscoveryHit).filter_by(campaign_id=campaign_id).delete()
        campaign = session.get(Campaign, campaign_id)
        if campaign:
            session.delete(campaign)
    return RedirectResponse("/", status_code=303)


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail(request: Request, campaign_id: uuid.UUID) -> HTMLResponse:
    with get_session() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            return HTMLResponse("Campaign not found", status_code=404)
        counts = get_stage_counts(session, campaign_id)

    task_entry = registry.get(campaign_id)
    task_running = registry.is_running(campaign_id)
    active_stage = task_entry.stage if task_entry and task_entry.is_running else None
    task_error = task_entry.error if task_entry and not task_entry.is_running else None
    task_elapsed = (
        round(task_entry.elapsed_seconds or 0)
        if task_entry and not task_entry.is_running
        else None
    )

    # Fetch last-run info from DB for each stage (survives server restarts)
    last_runs = {
        key: get_last_run(campaign_id, key)
        for key, _label in PIPELINE_STAGES
    }

    stage_rows = _build_stage_rows(counts)

    return templates.TemplateResponse(
        request,
        "campaigns/detail.html",
        {
            "campaign": campaign,
            "campaign_id": campaign_id,
            "stage_rows": stage_rows,
            "counts": counts,
            "task_running": task_running,
            "active_stage": active_stage,
            "task_error": task_error,
            "task_elapsed": task_elapsed,
            "last_runs": last_runs,
            "stage_error_hints": STAGE_ERROR_HINTS,
        },
    )
