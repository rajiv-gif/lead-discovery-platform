"""Pipeline stage run endpoints.

Each POST starts the corresponding runner in a background thread via the
task registry. Returns an HTML partial (the stage-status table) immediately
so the UI can begin polling for progress.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.dashboard.deps import STAGE_ERROR_HINTS, get_stage_counts, templates
from src.dashboard.persistence import get_last_run, on_finish, on_start
from src.dashboard.tasks import registry
from src.db.session import get_session
from src.discovery.runner import run_discovery_for_campaign
from src.extraction.runner import run_extraction_for_campaign
from src.scraper.runner import run_scrape_for_campaign
from src.scoring.runner import run_scoring_for_campaign
from src.verification.runner import run_verification_for_campaign

log = logging.getLogger(__name__)

router = APIRouter()

_RUNNERS = {
    "discover": run_discovery_for_campaign,
    "scrape": run_scrape_for_campaign,
    "extract": run_extraction_for_campaign,
    "verify": run_verification_for_campaign,
    "score": run_scoring_for_campaign,
}


def _stage_partial(
    request: Request,
    campaign_id: uuid.UUID,
    counts: dict,
    task_running: bool,
    active_stage: str | None,
    task_error: str | None,
    task_elapsed: int | None = None,
) -> HTMLResponse:
    from src.dashboard.routes.detail import PIPELINE_STAGES, _build_stage_rows

    stage_rows = _build_stage_rows(counts)
    last_runs = {
        key: get_last_run(campaign_id, key)
        for key, _label in PIPELINE_STAGES
    }
    return templates.TemplateResponse(
        request,
        "partials/stage_status.html",
        {
            "campaign_id": campaign_id,
            "stage_rows": stage_rows,
            "task_running": task_running,
            "active_stage": active_stage,
            "task_error": task_error,
            "task_elapsed": task_elapsed,
            "last_runs": last_runs,
            "stage_error_hints": STAGE_ERROR_HINTS,
        },
    )


@router.post("/campaigns/{campaign_id}/run/{stage}", response_class=HTMLResponse)
async def run_stage(
    request: Request, campaign_id: uuid.UUID, stage: str
) -> HTMLResponse:
    if stage not in _RUNNERS:
        return HTMLResponse(f"Unknown stage: {stage!r}", status_code=400)

    # --- Concurrency guard: only one stage per campaign at a time ---
    if registry.is_running(campaign_id):
        entry = registry.get(campaign_id)
        active = entry.stage if entry else "unknown"
        log.info(
            "Run %r blocked for campaign %s — stage %r already running",
            stage, campaign_id, active,
        )
        with get_session() as session:
            counts = get_stage_counts(session, campaign_id)
        return _stage_partial(
            request, campaign_id, counts,
            task_running=True,
            active_stage=active,
            task_error=None,
        )

    # --- Dispatch to thread pool ---
    fn = _RUNNERS[stage]
    try:
        registry.start(
            campaign_id, stage, fn, campaign_id,
            on_start=on_start,
            on_finish=on_finish,
        )
        log.info("Started stage %r for campaign %s", stage, campaign_id)
    except RuntimeError as exc:
        # Race condition: became running between the is_running check and start()
        log.warning("Failed to start stage %r for campaign %s: %s", stage, campaign_id, exc)

    with get_session() as session:
        counts = get_stage_counts(session, campaign_id)

    task_entry = registry.get(campaign_id)
    task_running = registry.is_running(campaign_id)
    active_stage = task_entry.stage if task_entry and task_entry.is_running else None

    return _stage_partial(
        request, campaign_id, counts,
        task_running=task_running,
        active_stage=active_stage,
        task_error=None,
    )
