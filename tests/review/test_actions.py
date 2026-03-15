"""Unit tests for src/review/actions.py — pure function tests, no DB."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.models.enums import LeadStatus, ReviewStatus
from src.review.actions import approve_lead, mark_needs_edit, reject_lead


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead(status=LeadStatus.NEW, review_status=ReviewStatus.PENDING):
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.status = status
    lead.review_status = review_status
    lead.review_decided_at = None
    lead.qualified_at = None
    return lead


def _make_session(lead):
    session = MagicMock()
    session.get.return_value = lead
    return session


# ---------------------------------------------------------------------------
# approve_lead tests
# ---------------------------------------------------------------------------


def test_approve_sets_review_status_approved():
    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(lead)

    result = approve_lead(session, lead.id)

    assert result.review_status == ReviewStatus.APPROVED


def test_approve_transitions_new_to_qualified():
    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(lead)

    approve_lead(session, lead.id)

    assert lead.status == LeadStatus.QUALIFIED


def test_approve_sets_qualified_at():
    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(lead)

    approve_lead(session, lead.id)

    assert lead.qualified_at is not None


def test_approve_sets_review_decided_at():
    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(lead)

    approve_lead(session, lead.id)

    assert lead.review_decided_at is not None


def test_approve_preserves_qualified_status():
    """Approving an already-qualified lead must not downgrade its status."""
    lead = _make_lead(status=LeadStatus.QUALIFIED)
    session = _make_session(lead)

    approve_lead(session, lead.id)

    assert lead.status == LeadStatus.QUALIFIED
    assert lead.review_status == ReviewStatus.APPROVED


def test_approve_preserves_contacted_status():
    lead = _make_lead(status=LeadStatus.CONTACTED)
    session = _make_session(lead)

    approve_lead(session, lead.id)

    assert lead.status == LeadStatus.CONTACTED


def test_approve_preserves_converted_status():
    lead = _make_lead(status=LeadStatus.CONVERTED)
    session = _make_session(lead)

    approve_lead(session, lead.id)

    assert lead.status == LeadStatus.CONVERTED


def test_approve_disqualified_does_not_change_status(caplog):
    """Approving a DISQUALIFIED lead records approval but preserves status with warning."""
    import logging

    lead = _make_lead(status=LeadStatus.DISQUALIFIED)
    session = _make_session(lead)

    with caplog.at_level(logging.WARNING, logger="src.review.actions"):
        approve_lead(session, lead.id)

    assert lead.status == LeadStatus.DISQUALIFIED  # unchanged
    assert lead.review_status == ReviewStatus.APPROVED
    assert any("DISQUALIFIED" in m for m in caplog.messages)


def test_approve_raises_when_lead_not_found():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(ValueError, match="not found"):
        approve_lead(session, uuid.uuid4())


# ---------------------------------------------------------------------------
# reject_lead tests
# ---------------------------------------------------------------------------


def test_reject_sets_review_status_rejected():
    lead = _make_lead()
    session = _make_session(lead)

    reject_lead(session, lead.id)

    assert lead.review_status == ReviewStatus.REJECTED


def test_reject_sets_status_disqualified():
    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(lead)

    reject_lead(session, lead.id)

    assert lead.status == LeadStatus.DISQUALIFIED


def test_reject_sets_review_decided_at():
    lead = _make_lead()
    session = _make_session(lead)

    reject_lead(session, lead.id)

    assert lead.review_decided_at is not None


def test_reject_raises_when_lead_not_found():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(ValueError, match="not found"):
        reject_lead(session, uuid.uuid4())


# ---------------------------------------------------------------------------
# mark_needs_edit tests
# ---------------------------------------------------------------------------


def test_needs_edit_sets_review_status():
    lead = _make_lead()
    session = _make_session(lead)

    mark_needs_edit(session, lead.id)

    assert lead.review_status == ReviewStatus.NEEDS_EDIT


def test_needs_edit_does_not_change_lead_status():
    """mark_needs_edit should not alter the pipeline status."""
    lead = _make_lead(status=LeadStatus.NEW)
    session = _make_session(lead)

    mark_needs_edit(session, lead.id)

    assert lead.status == LeadStatus.NEW  # unchanged


def test_needs_edit_sets_review_decided_at():
    lead = _make_lead()
    session = _make_session(lead)

    mark_needs_edit(session, lead.id)

    assert lead.review_decided_at is not None


def test_needs_edit_raises_when_lead_not_found():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(ValueError, match="not found"):
        mark_needs_edit(session, uuid.uuid4())
