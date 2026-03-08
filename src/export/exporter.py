"""export: write approved leads to an output format.

Phase 1 target: CSV with a fixed column order matching the Lead schema.

Future targets: JSON, HubSpot, Salesforce.

See docs/pipeline.md — Stage 7: Export.
"""
from __future__ import annotations

from pathlib import Path


# Column order for CSV export
CSV_COLUMNS = [
    "id",
    "company_name",
    "website",
    "email",
    "phone",
    "address",
    "city",
    "state",
    "country",
    "industry",
    "description",
    "linkedin_url",
    "score",
    "score_band",
    "reviewer_notes",
    "created_at",
]


def export_to_csv(output_path: Path, min_score: float = 0.0) -> int:
    """Write all approved leads to a CSV file.

    Returns the number of leads exported.
    Not yet implemented.
    """
    raise NotImplementedError
