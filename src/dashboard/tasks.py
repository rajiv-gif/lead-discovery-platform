"""In-memory task registry for dashboard pipeline stage execution.

IMPORTANT: This registry is single-process and NOT multi-worker safe.
Task state is held in memory and does not survive server restarts.
Run the dashboard with a single Uvicorn worker (the default ``--workers 1``).

Design rationale
----------------
FastAPI's built-in ``BackgroundTasks`` are fire-and-forget with no status
tracking. Instead we use ``asyncio.create_task(asyncio.to_thread(fn, *args))``:

- The blocking runner function executes in a thread-pool worker.
- The asyncio Task object is stored in the registry so we can check completion.
- Done callbacks capture the finish time and any exception.
- Only one stage per campaign may run at a time (enforced by ``start()``).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class TaskEntry:
    """State for one in-flight (or recently completed) pipeline stage run."""

    stage: str
    task: asyncio.Task
    started_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return not self.task.done()

    @property
    def status(self) -> str:
        if self.is_running:
            return "running"
        if self.error:
            return "failed"
        return "done"

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if self.finished_at is None:
            return (datetime.now(tz=timezone.utc) - self.started_at).total_seconds()
        return (self.finished_at - self.started_at).total_seconds()


class TaskRegistry:
    """Registry of in-flight pipeline tasks keyed by campaign UUID.

    Single-process only. Not persisted. Not multi-worker safe.
    Only one stage per campaign may be active at a time.
    """

    def __init__(self) -> None:
        # campaign_id → most recent TaskEntry for that campaign
        self._tasks: dict[uuid.UUID, TaskEntry] = {}

    def is_running(self, campaign_id: uuid.UUID) -> bool:
        """Return True if a stage is currently running for this campaign."""
        entry = self._tasks.get(campaign_id)
        return entry is not None and entry.is_running

    def get(self, campaign_id: uuid.UUID) -> Optional[TaskEntry]:
        """Return the most recent TaskEntry for this campaign, or None."""
        return self._tasks.get(campaign_id)

    def start(
        self,
        campaign_id: uuid.UUID,
        stage: str,
        fn: Callable,
        *args: Any,
    ) -> TaskEntry:
        """Dispatch *fn(*args)* in a thread and register the resulting task.

        Args:
            campaign_id: Campaign this stage run belongs to.
            stage: Human-readable stage name (e.g. ``"scrape"``).
            fn: Blocking callable to run (a pipeline runner function).
            *args: Positional arguments forwarded to *fn*.

        Returns:
            The new ``TaskEntry``.

        Raises:
            RuntimeError: If a stage is already running for *campaign_id*.
        """
        if self.is_running(campaign_id):
            existing = self._tasks[campaign_id]
            raise RuntimeError(
                f"Stage {existing.stage!r} is already running for campaign {campaign_id}. "
                "Wait for it to complete before starting another stage."
            )

        task = asyncio.create_task(asyncio.to_thread(fn, *args))
        entry = TaskEntry(
            stage=stage,
            task=task,
            started_at=datetime.now(tz=timezone.utc),
        )
        self._tasks[campaign_id] = entry

        def _on_done(t: asyncio.Task) -> None:
            entry.finished_at = datetime.now(tz=timezone.utc)
            elapsed = entry.elapsed_seconds
            if t.cancelled():
                entry.error = "Task was cancelled"
                log.warning(
                    "Pipeline stage %r for campaign %s was cancelled after %.1fs",
                    stage, campaign_id, elapsed,
                )
            elif t.exception() is not None:
                entry.error = str(t.exception())
                log.error(
                    "Pipeline stage %r for campaign %s failed after %.1fs: %s",
                    stage, campaign_id, elapsed, entry.error,
                )
            else:
                log.info(
                    "Pipeline stage %r for campaign %s completed in %.1fs",
                    stage, campaign_id, elapsed,
                )

        task.add_done_callback(_on_done)
        return entry

    def clear(self, campaign_id: uuid.UUID) -> None:
        """Remove the registry entry for a campaign (only if not running)."""
        if not self.is_running(campaign_id):
            self._tasks.pop(campaign_id, None)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

# Single-process, in-memory — not safe for multi-worker deployments.
# Run uvicorn with --workers 1 (the default).
registry = TaskRegistry()
