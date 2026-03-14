"""CSV writer helper for lead exports."""
from __future__ import annotations

import csv
from pathlib import Path


def write_csv(rows: list[dict], path: Path, fieldnames: list[str]) -> int:
    """Write *rows* to a CSV file at *path*.

    Creates parent directories as needed. Returns the number of data rows
    written. Always writes the header row, even when *rows* is empty.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return len(rows)
