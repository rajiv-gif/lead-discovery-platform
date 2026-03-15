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

from src.dashboard.deps import get_stage_counts, templates
from src.dashboard.routes.detail import _build_stage_rows
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
        },
    )
