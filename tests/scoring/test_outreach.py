"""Tests for outreach transition helpers in src/scoring/deriver.py."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from src.models.enums import LeadStatus
from src.scoring.deriver import mark_churned, mark_contacted, mark_converted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead(status: LeadStatus):
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.status = status
    lead.contacted_at = None
    lead.converted_at = None
    return lead


def _make_session(lead=None):
    session = MagicMock()
    session.get.side_effect = lambda cls, id_: lead if lead and id_ == lead.id else None
    return session


# ---------------------------------------------------------------------------
# mark_contacted tests
# ---------------------------------------------------------------------------


def test_mark_contacted_from_qualified():
    lead = _make_lead(LeadStatus.QUALIFIED)
    session = _make_session(lead)

    result = mark_contacted(session, lead.id)

    assert result.status == LeadStatus.CONTACTED
    assert result.contacted_at is not None
    session.commit.assert_called_once()


def test_mark_contacted_from_new_raises():
    lead = _make_lead(LeadStatus.NEW)
    session = _make_session(lead)

    with pytest.raises(ValueError, match="Cannot transition"):
        mark_contacted(session, lead.id)


def test_mark_contacted_from_already_contacted_raises():
    lead = _make_lead(LeadStatus.CONTACTED)
    session = _make_session(lead)

    with pytest.raises(ValueError, match="Cannot transition"):
        mark_contacted(session, lead.id)


# ---------------------------------------------------------------------------
# mark_converted tests
# ---------------------------------------------------------------------------


def test_mark_converted_from_contacted():
    lead = _make_lead(LeadStatus.CONTACTED)
    session = _make_session(lead)

    result = mark_converted(session, lead.id)

    assert result.status == LeadStatus.CONVERTED
    assert result.converted_at is not None
    session.commit.assert_called_once()


def test_mark_converted_from_qualified_raises():
    lead = _make_lead(LeadStatus.QUALIFIED)
    session = _make_session(lead)

    with pytest.raises(ValueError, match="Cannot transition"):
        mark_converted(session, lead.id)


# ---------------------------------------------------------------------------
# mark_churned tests
# ---------------------------------------------------------------------------


def test_mark_churned_from_contacted():
    lead = _make_lead(LeadStatus.CONTACTED)
    session = _make_session(lead)

    result = mark_churned(session, lead.id)

    assert result.status == LeadStatus.CHURNED
    session.commit.assert_called_once()


def test_mark_churned_from_converted():
    lead = _make_lead(LeadStatus.CONVERTED)
    session = _make_session(lead)

    result = mark_churned(session, lead.id)

    assert result.status == LeadStatus.CHURNED
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


def test_mark_contacted_lead_not_found_raises():
    session = _make_session(lead=None)
    unknown_id = uuid.uuid4()

    with pytest.raises(ValueError, match="Lead not found"):
        mark_contacted(session, unknown_id)
