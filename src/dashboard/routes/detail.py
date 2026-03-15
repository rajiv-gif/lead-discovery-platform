"""Campaign detail page route."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.dashboard.deps import STAGE_ERROR_HINTS, get_stage_counts, templates
from src.dashboard.persistence import get_last_run
from src.dashboard.tasks import registry
from src.db.session import get_session
from src.models.campaign import Campaign

router = APIRouter()

# Ordered list of pipeline stages shown in the detail page table.
PIPELINE_STAGES = [
    ("discover", "Discovery"),
    ("scrape", "Scrape"),
    ("extract", "Extract"),
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
