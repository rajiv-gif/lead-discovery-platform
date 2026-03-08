"""pipeline: orchestrate all stages end-to-end.

Creates a ``Run`` record, calls each stage in order, and updates
``Run.stage_counts`` and ``Run.status`` as stages complete.

Supports resuming from a given stage via ``from_stage``.

Stages in order:
  discover → scrape → extract → verify → score → review → export

See docs/pipeline.md for full stage definitions.
"""
from __future__ import annotations

STAGES = ["discover", "scrape", "extract", "verify", "score", "review", "export"]


def run_pipeline(seed_file: str, from_stage: str | None = None) -> str:
    """Execute the full pipeline for a seed URL file.

    Creates a new ``Run`` record and processes all stages.
    Returns the ``Run.id``.
    Not yet implemented.
    """
    raise NotImplementedError
