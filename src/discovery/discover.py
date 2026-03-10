"""discovery — public interface for the Phase 1 discovery stage.

Phase 1 discovery uses the Google Places API. The implementation lives in:
  - ``src/discovery/places.py``     — PlacesClient
  - ``src/discovery/strategies.py`` — GeoQuery builders
  - ``src/discovery/upsert.py``     — company upsert and hit creation
  - ``src/discovery/runner.py``     — campaign orchestration

See docs/pipeline.md — Stage 1: Discovery.
"""
from __future__ import annotations

# Re-export the primary entry point so callers can import from this module.
from src.discovery.runner import DiscoverySummary, run_discovery_for_campaign

__all__ = ["run_discovery_for_campaign", "DiscoverySummary"]
