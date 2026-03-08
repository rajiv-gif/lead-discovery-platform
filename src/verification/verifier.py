"""verification: validate extracted lead fields.

For each ``Lead`` with ``extraction_status = extracted``:
  - Email: format check + MX record lookup
  - Phone: parse and normalize to E.164
  - Website: HTTP reachability check
  - Duplicate: detect against existing approved leads

Sets ``Lead.verification_status`` to ``verified``, ``partial``, or ``failed``.

See docs/pipeline.md — Stage 4: Verification.
"""
from __future__ import annotations


def verify_lead(lead_id: str) -> str:
    """Validate all fields for a single lead.

    Returns the resulting ``verification_status``.
    Not yet implemented.
    """
    raise NotImplementedError


def verify_extracted(run_id: str) -> tuple[int, int]:
    """Verify all extracted leads for a run.

    Returns ``(succeeded, failed)``.
    Not yet implemented.
    """
    raise NotImplementedError
