"""scraper: public re-exports for Phase 2 scraping stage.

Fetches pages for pending discovery hits, classifies them, extracts text,
and persists results to disk (raw HTML + .txt) and PostgreSQL (metadata +
extracted text).

See ``runner.py`` for the main entry point.
"""
from __future__ import annotations

from src.scraper.runner import ScrapeSummary, run_scrape_for_campaign

__all__ = ["run_scrape_for_campaign", "ScrapeSummary"]
