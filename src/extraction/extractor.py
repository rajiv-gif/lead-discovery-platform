"""extraction: LLM-based field extraction from raw HTML.

For each ``Source`` with status ``fetched``:
  1. Read HTML from disk
  2. Pre-process (strip scripts/styles, truncate to token budget)
  3. Call LLM with structured output prompt
  4. Write prompt + raw response to ``data/llm_runs/<extraction_run_id>/``
  5. Parse response into a ``Lead`` record
  6. Persist ``ExtractionRun`` metadata

See docs/extraction-strategy.md for prompt design and field schema.
"""
from __future__ import annotations


def extract_source(source_id: str) -> str | None:
    """Run LLM extraction for a single source.

    Returns the created ``Lead.id`` on success, or ``None`` on failure.
    Not yet implemented.
    """
    raise NotImplementedError


def extract_pending(run_id: str) -> tuple[int, int]:
    """Extract all fetched sources for a run.

    Returns ``(succeeded, failed)``.
    Not yet implemented.
    """
    raise NotImplementedError
