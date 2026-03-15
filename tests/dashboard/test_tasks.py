"""Unit tests for the in-memory task registry."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.dashboard.tasks import TaskEntry, TaskRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_task(done: bool = False, exc=None) -> MagicMock:
    task = MagicMock(spec=asyncio.Task)
    task.done.return_value = done
    task.cancelled.return_value = False
    task.exception.return_value = exc
    task.add_done_callback = MagicMock()
    return task


def _make_entry(stage: str = "scrape", done: bool = False) -> TaskEntry:
    return TaskEntry(
        stage=stage,
        task=_mock_task(done=done),
        started_at=datetime.now(tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# TaskEntry property tests
# ---------------------------------------------------------------------------


def test_task_entry_is_running_when_not_done():
    entry = _make_entry(done=False)
    assert entry.is_running is True


def test_task_entry_not_running_when_done():
    entry = _make_entry(done=True)
    assert entry.is_running is False


def test_task_entry_status_running():
    entry = _make_entry(done=False)
    assert entry.status == "running"


def test_task_entry_status_done():
    entry = _make_entry(done=True)
    assert entry.status == "done"


def test_task_entry_status_failed():
    entry = _make_entry(done=True)
    entry.error = "Something went wrong"
    assert entry.status == "failed"


# ---------------------------------------------------------------------------
# TaskRegistry tests
# ---------------------------------------------------------------------------


def test_registry_is_running_false_when_empty():
    reg = TaskRegistry()
    assert reg.is_running(uuid.uuid4()) is False


def test_registry_get_returns_none_when_empty():
    reg = TaskRegistry()
    assert reg.get(uuid.uuid4()) is None


def test_registry_start_stores_entry():
    reg = TaskRegistry()
    cid = uuid.uuid4()

    mock_task = _mock_task(done=False)
    with patch("asyncio.create_task", return_value=mock_task):
        entry = reg.start(cid, "scrape", lambda: None)

    assert reg.get(cid) is entry
    assert entry.stage == "scrape"


def test_registry_is_running_true_after_start():
    reg = TaskRegistry()
    cid = uuid.uuid4()

    mock_task = _mock_task(done=False)
    with patch("asyncio.create_task", return_value=mock_task):
        reg.start(cid, "scrape", lambda: None)

    assert reg.is_running(cid) is True


def test_registry_prevents_concurrent_runs():
    """Starting a second stage for the same campaign raises RuntimeError."""
    reg = TaskRegistry()
    cid = uuid.uuid4()

    mock_task = _mock_task(done=False)
    with patch("asyncio.create_task", return_value=mock_task):
        reg.start(cid, "scrape", lambda: None)

        with pytest.raises(RuntimeError, match="already running"):
            reg.start(cid, "extract", lambda: None)


def test_registry_allows_new_run_after_completion():
    """A new stage can start once the previous task is done."""
    reg = TaskRegistry()
    cid = uuid.uuid4()

    done_task = _mock_task(done=True)
    # Insert a completed entry directly
    reg._tasks[cid] = TaskEntry(
        stage="scrape",
        task=done_task,
        started_at=datetime.now(tz=timezone.utc),
        finished_at=datetime.now(tz=timezone.utc),
    )

    assert reg.is_running(cid) is False

    new_task = _mock_task(done=False)
    with patch("asyncio.create_task", return_value=new_task):
        entry = reg.start(cid, "extract", lambda: None)

    assert entry.stage == "extract"
    assert reg.is_running(cid) is True


def test_registry_different_campaigns_independent():
    """Two campaigns can have concurrent tasks without interfering."""
    reg = TaskRegistry()
    cid1, cid2 = uuid.uuid4(), uuid.uuid4()

    t1 = _mock_task(done=False)
    t2 = _mock_task(done=False)

    with patch("asyncio.create_task", side_effect=[t1, t2]):
        reg.start(cid1, "scrape", lambda: None)
        reg.start(cid2, "extract", lambda: None)

    assert reg.is_running(cid1) is True
    assert reg.is_running(cid2) is True


def test_registry_clear_removes_done_entry():
    reg = TaskRegistry()
    cid = uuid.uuid4()

    reg._tasks[cid] = TaskEntry(
        stage="scrape",
        task=_mock_task(done=True),
        started_at=datetime.now(tz=timezone.utc),
        finished_at=datetime.now(tz=timezone.utc),
    )

    reg.clear(cid)
    assert reg.get(cid) is None


def test_registry_clear_does_not_remove_running_entry():
    reg = TaskRegistry()
    cid = uuid.uuid4()

    reg._tasks[cid] = TaskEntry(
        stage="scrape",
        task=_mock_task(done=False),
        started_at=datetime.now(tz=timezone.utc),
    )

    reg.clear(cid)  # Should be a no-op
    assert reg.get(cid) is not None


def test_done_callback_captures_error():
    """The done callback sets entry.error when the task raises."""
    reg = TaskRegistry()
    cid = uuid.uuid4()

    # Capture the callback so we can invoke it manually
    captured_callback = None

    def fake_create_task(coro):
        task = _mock_task(done=True)
        task.cancelled.return_value = False
        task.exception.return_value = ValueError("boom")

        def add_cb(cb):
            nonlocal captured_callback
            captured_callback = cb

        task.add_done_callback = add_cb
        return task

    with patch("asyncio.create_task", side_effect=fake_create_task):
        entry = reg.start(cid, "scrape", lambda: None)

    assert captured_callback is not None
    captured_callback(entry.task)

    assert entry.error == "boom"
    assert entry.finished_at is not None
