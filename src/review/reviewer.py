"""review: human-in-the-loop lead review.

Presents scored leads one at a time via the terminal.
Reviewer chooses: approve / reject / skip / edit notes.

Sets ``Lead.review_status`` to ``approved``, ``rejected``, or leaves
it ``pending`` on skip.

See docs/pipeline.md — Stage 6: Review.
"""
from __future__ import annotations


def review_loop(min_score: float = 25.0) -> None:
    """Interactive CLI loop for reviewing scored leads.

    Iterates over leads with ``review_status = pending`` and score >= min_score.
    Not yet implemented.
    """
    raise NotImplementedError
