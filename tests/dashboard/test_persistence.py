"""Unit tests for src/dashboard/persistence.py and Phase 7 additions.

All tests mock the DB session so no real database is required.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from src.dashboard.persistence import _run_ids, get_last_run, on_finish, on_start
from src.dashboard.tasks import TaskEntry, TaskRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_task(done: bool = False) -> MagicMock:
    task = MagicMock()
    task.done.return_value = done
    task.cancelled.return_value = False
    task.exception.return_value = None
    task.add_done_callback = MagicMock()
    return task


def _make_entry(stage: str = "scrape", done: bool = False, error: str | None = None) -> TaskEntry:
    entry = TaskEntry(
        stage=stage,
        task=_mock_task(done=done),
        started_at=datetime.now(tz=timezone.utc),
        finished_at=datetime.now(tz=timezone.utc) if done else None,
        error=error,
    )
    return entry


@contextmanager
def _mock_get_session(session):
    yield session


# ---------------------------------------------------------------------------
# on_start tests
# ---------------------------------------------------------------------------


def test_on_start_inserts_pipeline_run():
    """on_start should add a PipelineRun to the session."""
    cid = uuid.uuid4()
    entry = _make_entry(stage="scrape")

    run_mock = MagicMock()
    run_mock.id = uuid.uuid4()

    session = MagicMock()
    session.add = MagicMock()
    session.flush = MagicMock()

    def _flush_sets_id():
        # simulate flush populating id
        pass

    with patch("src.dashboard.persistence.get_session", return_value=_mock_get_session(session)), \
         patch("src.dashboard.persistence.PipelineRun", return_value=run_mock) as MockRun:
        on_start(cid, entry)

    session.add.assert_called_once_with(run_mock)
    session.flush.assert_called_once()


def test_on_start_caches_run_id():
    """on_start should cache the run id for later use by on_finish."""
    cid = uuid.uuid4()
    entry = _make_entry(stage="extract")

    run_mock = MagicMock()
    run_mock.id = uuid.uuid4()

    session = MagicMock()

    # clear any leftover state
    _run_ids.pop((cid, "extract"), None)

    with patch("src.dashboard.persistence.get_session", return_value=_mock_get_session(session)), \
         patch("src.dashboard.persistence.PipelineRun", return_value=run_mock):
        on_start(cid, entry)

    assert _run_ids.get((cid, "extract")) == run_mock.id

    # cleanup
    _run_ids.pop((cid, "extract"), None)


def test_on_start_swallows_db_error(caplog):
    """on_start should log and not raise if the DB write fails."""
    import logging

    cid = uuid.uuid4()
    entry = _make_entry(stage="scrape")

    with patch("src.dashboard.persistence.get_session", side_effect=RuntimeError("DB down")):
        with caplog.at_level(logging.ERROR, logger="src.dashboard.persistence"):
            on_start(cid, entry)  # must not raise

    assert any("Failed to persist pipeline_run start" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# on_finish tests
# ---------------------------------------------------------------------------


def test_on_finish_updates_status_done():
    """on_finish should update status to 'done' for a successful run."""
    cid = uuid.uuid4()
    entry = _make_entry(stage="score", done=True, error=None)
    run_id = uuid.uuid4()
    _run_ids[(cid, "score")] = run_id

    run_mock = MagicMock()
    session = MagicMock()
    session.get.return_value = run_mock

    with patch("src.dashboard.persistence.get_session", return_value=_mock_get_session(session)):
        on_finish(cid, entry)

    assert run_mock.status == "done"
    assert run_mock.finished_at == entry.finished_at
    assert run_mock.error is None


def test_on_finish_updates_status_failed():
    """on_finish should update status to 'failed' when entry has an error."""
    cid = uuid.uuid4()
    entry = _make_entry(stage="verify", done=True, error="Boom!")
    run_id = uuid.uuid4()
    _run_ids[(cid, "verify")] = run_id

    run_mock = MagicMock()
    session = MagicMock()
    session.get.return_value = run_mock

    with patch("src.dashboard.persistence.get_session", return_value=_mock_get_session(session)):
        on_finish(cid, entry)

    assert run_mock.status == "failed"
    assert run_mock.error == "Boom!"


def test_on_finish_updates_status_cancelled():
    """on_finish should set status to 'cancelled' for a cancelled task."""
    cid = uuid.uuid4()
    entry = _make_entry(stage="discover", done=True, error="Task was cancelled")
    run_id = uuid.uuid4()
    _run_ids[(cid, "discover")] = run_id

    run_mock = MagicMock()
    session = MagicMock()
    session.get.return_value = run_mock

    with patch("src.dashboard.persistence.get_session", return_value=_mock_get_session(session)):
        on_finish(cid, entry)

    assert run_mock.status == "cancelled"


def test_on_finish_no_cached_id_logs_warning(caplog):
    """on_finish without a cached run id should warn and be a no-op."""
    import logging

    cid = uuid.uuid4()
    entry = _make_entry(stage="scrape", done=True)
    # Ensure no cached id
    _run_ids.pop((cid, "scrape"), None)

    with caplog.at_level(logging.WARNING, logger="src.dashboard.persistence"):
        on_finish(cid, entry)  # must not raise

    assert any("No pipeline_run id cached" in m for m in caplog.messages)


def test_on_finish_swallows_db_error(caplog):
    """on_finish should log and not raise if the DB write fails."""
    import logging

    cid = uuid.uuid4()
    entry = _make_entry(stage="extract", done=True)
    _run_ids[(cid, "extract")] = uuid.uuid4()

    with patch("src.dashboard.persistence.get_session", side_effect=RuntimeError("gone")):
        with caplog.at_level(logging.ERROR, logger="src.dashboard.persistence"):
            on_finish(cid, entry)  # must not raise

    assert any("Failed to persist pipeline_run finish" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# on_start / on_finish hooks wired into TaskRegistry
# ---------------------------------------------------------------------------


def test_registry_calls_on_start_hook():
    """TaskRegistry.start() should call on_start immediately after entry creation."""
    reg = TaskRegistry()
    cid = uuid.uuid4()
    calls = []

    def hook(campaign_id, entry):
        calls.append((campaign_id, entry.stage))

    mock_task = _mock_task(done=False)
    with patch("asyncio.create_task", return_value=mock_task):
        reg.start(cid, "scrape", lambda: None, on_start=hook)

    assert calls == [(cid, "scrape")]


def test_registry_calls_on_finish_hook_via_done_callback():
    """on_finish hook should be called inside the done callback."""
    reg = TaskRegistry()
    cid = uuid.uuid4()
    finish_calls = []
    captured_callback = None

    def fake_create_task(coro):
        task = _mock_task(done=True)
        task.cancelled.return_value = False
        task.exception.return_value = None

        def add_cb(cb):
            nonlocal captured_callback
            captured_callback = cb

        task.add_done_callback = add_cb
        return task

    def finish_hook(campaign_id, entry):
        finish_calls.append((campaign_id, entry.stage))

    with patch("asyncio.create_task", side_effect=fake_create_task):
        entry = reg.start(cid, "discover", lambda: None, on_finish=finish_hook)

    assert captured_callback is not None
    captured_callback(entry.task)

    assert finish_calls == [(cid, "discover")]


# ---------------------------------------------------------------------------
# /healthz endpoint
# ---------------------------------------------------------------------------


def test_healthz_returns_200():
    from fastapi.testclient import TestClient

    from src.dashboard.app import app

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# STAGE_ERROR_HINTS
# ---------------------------------------------------------------------------


def test_stage_error_hints_covers_all_pipeline_stages():
    """Every pipeline stage should have a hint string."""
    from src.dashboard.deps import STAGE_ERROR_HINTS
    from src.dashboard.routes.detail import PIPELINE_STAGES

    for key, _label in PIPELINE_STAGES:
        assert key in STAGE_ERROR_HINTS, f"Missing hint for stage {key!r}"
        assert STAGE_ERROR_HINTS[key], f"Empty hint for stage {key!r}"


# ---------------------------------------------------------------------------
# PipelineRun model sanity check
# ---------------------------------------------------------------------------


def test_pipeline_run_model_has_expected_columns():
    """PipelineRun must expose the columns used by the dashboard."""
    from src.models.pipeline_run import PipelineRun

    columns = {c.name for c in PipelineRun.__table__.columns}
    for expected in ("id", "campaign_id", "stage", "status", "started_at",
                     "finished_at", "elapsed_seconds", "error"):
        assert expected in columns, f"Missing column: {expected!r}"


def test_pipeline_run_campaign_id_is_indexed():
    """campaign_id column should be indexed for fast per-campaign queries."""
    from src.models.pipeline_run import PipelineRun

    indexed_cols = {
        col.name
        for idx in PipelineRun.__table__.indexes
        for col in idx.columns
    }
    assert "campaign_id" in indexed_cols
