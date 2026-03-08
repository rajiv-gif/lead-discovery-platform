"""scoring: compute a quality score for each lead.

Score is 0–100, capped at 100. Bands:
  hot  >= 75  warm >= 50  cold >= 25  disqualified < 25

Four dimensions (see docs/scoring-model.md):
  1. Field completeness   (max 35)
  2. Verification quality (max 30)
  3. Source quality       (max 20)
  4. Extraction confidence (max 15, +5 bonus)

Scoring is a pure function: no network calls, no side effects beyond
writing the score back to the Lead record.
"""
from __future__ import annotations

from src.models.lead import Lead


SCORE_BANDS = {
    "hot": 75,
    "warm": 50,
    "cold": 25,
    # below 25 → disqualified
}


def score_lead(lead: Lead) -> tuple[float, str]:
    """Compute (score, score_band) for a lead.

    Does not persist — caller is responsible for writing back to DB.
    Not yet implemented.
    """
    raise NotImplementedError


def score_verified(run_id: str) -> tuple[int, int]:
    """Score all verified leads for a run.

    Returns ``(succeeded, failed)``.
    Not yet implemented.
    """
    raise NotImplementedError
