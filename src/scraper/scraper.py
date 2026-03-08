"""scraper: fetch pages and write raw HTML to disk.

For each ``Source`` with status ``pending``:
  1. HTTP GET the URL (with retry/backoff)
  2. Write HTML to ``data/pages/<hash>.html``
  3. Update ``Source.page_path``, ``status_code``, ``fetched_at``, ``status``

Raw HTML is never stored in PostgreSQL — only the file path.

See docs/pipeline.md — Stage 2: Scraper.
"""
from __future__ import annotations


def scrape_source(source_id: str) -> None:
    """Fetch and persist a single source by ID.

    Not yet implemented.
    """
    raise NotImplementedError


def scrape_pending(run_id: str, limit: int = 0) -> tuple[int, int]:
    """Scrape all pending sources for a run.

    Returns ``(succeeded, failed)``.
    Not yet implemented.
    """
    raise NotImplementedError
