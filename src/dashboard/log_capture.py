"""Per-campaign log capture for live log streaming in the dashboard.

Attaches a FileHandler to the root logger when a pipeline stage starts,
writing to data/logs/<campaign_id>.log, then detaches when done.

Thread-safe: the handler is added/removed from the async event loop thread
via the on_start/on_finish hooks. The stage runner thread writes records
concurrently — Python's FileHandler uses an internal lock.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

LOG_DIR = Path("data/logs")

_HANDLER_PREFIX = "campaign_log_"
_FORMATTER = logging.Formatter(
    "%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


def _log_path(campaign_id: uuid.UUID) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{campaign_id}.log"


def start_capture(campaign_id: uuid.UUID, stage: str) -> None:
    """Write a stage header and attach a FileHandler for this campaign."""
    path = _log_path(campaign_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n▶  {stage.upper()}\n{'─' * 60}\n")

    handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    handler.setFormatter(_FORMATTER)
    handler.setLevel(logging.DEBUG)
    handler.set_name(f"{_HANDLER_PREFIX}{campaign_id}")
    logging.getLogger().addHandler(handler)


def stop_capture(campaign_id: uuid.UUID) -> None:
    """Flush, close and remove the FileHandler for this campaign."""
    root = logging.getLogger()
    name = f"{_HANDLER_PREFIX}{campaign_id}"
    for handler in root.handlers[:]:
        if handler.get_name() == name:
            handler.flush()
            handler.close()
            root.removeHandler(handler)
            break


def get_log_lines(campaign_id: uuid.UUID, n: int = 120) -> list[str]:
    """Return the last *n* lines of the campaign log, oldest first."""
    path = _log_path(campaign_id)
    if not path.exists():
        return []
    return path.read_text(errors="replace").splitlines()[-n:]
