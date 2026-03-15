"""Write-through helpers: persist pipeline stage run records to the DB.

These are the ``on_start`` and ``on_finish`` hooks passed to ``TaskRegistry.start()``.
Keeping them here (not in tasks.py) means the registry module stays free of DB
imports and remains straightforward to unit-test.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from src.db.session import get_session
from src.models.pipeline_run import PipelineRun

if TYPE_CHECKING:
    from src.dashboard.tasks import TaskEntry

log = logging.getLogger(__name__)

# Per-campaign, per-stage primary key cache so on_finish can UPDATE rather than INSERT.
# Keyed by (campaign_id, stage). Cleared implicitly on each new on_start call.
_run_ids: dict[tuple[uuid.UUID, str], uuid.UUID] = {}


def on_start(campaign_id: uuid.UUID, entry: "TaskEntry") -> None:
    """Insert a PipelineRun row with status='running' at stage start."""
    run = PipelineRun(
        campaign_id=campaign_id,
        stage=entry.stage,
        status="running",
        started_at=entry.started_at,
    )
    try:
        with get_session() as session:
            session.add(run)
            session.flush()
            _run_ids[(campaign_id, entry.stage)] = run.id
    except Exception:
        log.exception(
            "Failed to persist pipeline_run start for campaign %s stage %r",
            campaign_id, entry.stage,
        )


def on_finish(campaign_id: uuid.UUID, entry: "TaskEntry") -> None:
    """Update the PipelineRun row with final status, elapsed time, and error."""
    run_id = _run_ids.pop((campaign_id, entry.stage), None)
    if run_id is None:
        log.warning(
            "No pipeline_run id cached for campaign %s stage %r — skipping finish persist",
            campaign_id, entry.stage,
        )
        return

    status = "done"
    if entry.error == "Task was cancelled":
        status = "cancelled"
    elif entry.error is not None:
        status = "failed"

    try:
        with get_session() as session:
            run = session.get(PipelineRun, run_id)
            if run is None:
                log.warning("pipeline_run %s not found for update", run_id)
                return
            run.status = status
            run.finished_at = entry.finished_at
            run.elapsed_seconds = entry.elapsed_seconds
            run.error = entry.error
    except Exception:
        log.exception(
            "Failed to persist pipeline_run finish for campaign %s stage %r",
            campaign_id, entry.stage,
        )


def get_last_run(campaign_id: uuid.UUID, stage: str) -> PipelineRun | None:
    """Return the most recent PipelineRun for a campaign+stage, or None."""
    from sqlalchemy import select

    try:
        with get_session() as session:
            stmt = (
                select(PipelineRun)
                .where(
                    PipelineRun.campaign_id == campaign_id,
                    PipelineRun.stage == stage,
                )
                .order_by(PipelineRun.started_at.desc())
                .limit(1)
            )
            return session.execute(stmt).scalar_one_or_none()
    except Exception:
        log.exception(
            "Failed to query last pipeline_run for campaign %s stage %r",
            campaign_id, stage,
        )
        return None
