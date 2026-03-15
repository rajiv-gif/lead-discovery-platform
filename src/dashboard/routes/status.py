"""HTMX polling endpoint for campaign stage status.

The detail page polls this endpoint every 3 seconds while a stage is running.
Polling is driven by an element in the ``partials/stage_status.html`` partial
itself: when a task is running, the partial includes a polling trigger element;
when idle, that element is absent and polling stops naturally.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.dashboard.deps import STAGE_ERROR_HINTS, get_stage_counts, templates
from src.dashboard.persistence import get_last_run
from src.dashboard.routes.detail import PIPELINE_STAGES, _build_stage_rows
from src.dashboard.tasks import registry
from src.db.session import get_session

router = APIRouter()


@router.get("/campaigns/{campaign_id}/status", response_class=HTMLResponse)
async def campaign_status(request: Request, campaign_id: uuid.UUID) -> HTMLResponse:
    """Return the stage-status partial, updated with live DB counts.

    Called by the HTMX polling element in ``partials/stage_status.html``.
    """
    with get_session() as session:
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

    last_runs = {
        key: get_last_run(campaign_id, key)
        for key, _label in PIPELINE_STAGES
    }

    stage_rows = _build_stage_rows(counts)

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
