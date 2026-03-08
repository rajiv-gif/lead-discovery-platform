"""discovery: find candidate source URLs.

Reads seed input (e.g. a file of URLs) and writes ``Source`` records
to the database with status ``pending``.

See docs/pipeline.md — Stage 1: Discovery.
"""
from __future__ import annotations


def discover_from_file(path: str, run_id: str) -> int:
    """Load URLs from a newline-delimited file and persist as Source records.

    Returns the number of sources created.
    Not yet implemented.
    """
    raise NotImplementedError
