"""Dashboard route tests using FastAPI TestClient.

All tests mock ``get_session`` and the pipeline runner functions so no real
database or external API calls are made.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import app
from src.models.enums import (
    CampaignStatus,
    DiscoveryHitStatus,
    GeoMethod,
    LeadStatus,
    ReviewStatus,
    ScoreBand,
)

client = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Session mock helpers
# ---------------------------------------------------------------------------


@contextmanager
def _mock_session(session_obj):
    yield session_obj


def _make_campaign(campaign_id=None):
    c = MagicMock()
    c.id = campaign_id or uuid.uuid4()
    c.name = "Test Campaign"
    c.specialty = "dentists"
    c.description = None
    c.status = CampaignStatus.DRAFT
    c.geo_method = GeoMethod.CITY
    c.geo_city = "London"
    c.geo_country = "UK"
    c.created_at = datetime(2026, 3, 15, tzinfo=timezone.utc)
    return c


def _make_lead(campaign_id, company_id=None):
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.campaign_id = campaign_id
    lead.company_id = company_id or uuid.uuid4()
    lead.status = LeadStatus.NEW
    lead.review_status = ReviewStatus.PENDING
    lead.score = 70.0
    lead.score_band = ScoreBand.WARM
    lead.score_details = {}
    lead.review_decided_at = None
    return lead


def _zero_counts_session(campaign_id):
    """Session that returns a campaign and zero counts for all queries."""
    session = MagicMock()
    campaign = _make_campaign(campaign_id)
    session.get.return_value = campaign

    result = MagicMock()
    result.scalar.return_value = 0
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    session.scalar.return_value = 0
    return session


# ---------------------------------------------------------------------------
# Campaign list
# ---------------------------------------------------------------------------


def test_campaign_list_empty():
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    with patch("src.dashboard.routes.campaigns.get_session",
               return_value=_mock_session(session)):
        resp = client.get("/")

    assert resp.status_code == 200
    assert "No campaigns" in resp.text


def test_campaign_list_shows_campaigns():
    campaign = _make_campaign()
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [campaign]
    session.execute.return_value = result

    with patch("src.dashboard.routes.campaigns.get_session",
               return_value=_mock_session(session)):
        resp = client.get("/")

    assert resp.status_code == 200
    assert campaign.name in resp.text


# ---------------------------------------------------------------------------
# Campaign create form
# ---------------------------------------------------------------------------


def test_campaign_create_form_returns_200():
    resp = client.get("/campaigns/new")
    assert resp.status_code == 200
    assert "New campaign" in resp.text


def test_campaign_create_missing_name_returns_error():
    with patch("src.dashboard.routes.campaigns.get_session",
               return_value=_mock_session(MagicMock())):
        resp = client.post(
            "/campaigns/new",
            data={"name": "", "geo_method": "city", "city": "London", "country": "UK"},
            follow_redirects=False,
        )
    assert resp.status_code == 422
    assert "required" in resp.text.lower()


def test_campaign_create_redirects_on_success():
    cid = uuid.uuid4()
    campaign = _make_campaign(cid)
    session = MagicMock()
    session.flush.return_value = None
    session.add.return_value = None

    # Simulate flush setting the id
    def add_side(obj):
        obj.id = cid

    session.add.side_effect = add_side
    session.flush.return_value = None
    # After flush, campaign.id should be set
    # We need to patch the Campaign constructor behavior
    with patch("src.dashboard.routes.campaigns.get_session",
               return_value=_mock_session(session)):
        with patch("src.dashboard.routes.campaigns.Campaign") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.id = cid
            mock_cls.return_value = mock_instance
            resp = client.post(
                "/campaigns/new",
                data={
                    "name": "Test",
                    "geo_method": "city",
                    "city": "London",
                    "country": "UK",
                    "specialty": "dentists",
                },
                follow_redirects=False,
            )

    assert resp.status_code == 303
    assert f"/campaigns/{cid}" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Campaign detail
# ---------------------------------------------------------------------------


def test_campaign_detail_returns_200():
    cid = uuid.uuid4()
    session = _zero_counts_session(cid)

    with patch("src.dashboard.routes.detail.get_session",
               return_value=_mock_session(session)):
        with patch("src.dashboard.routes.detail.get_stage_counts",
                   return_value={
                       "total_hits": 10, "scraped": 8, "extracted": 6,
                       "verified_emails": 20, "total_leads": 5,
                       "pending_review": 3, "approved": 2,
                   }):
            resp = client.get(f"/campaigns/{cid}")

    assert resp.status_code == 200
    assert "Test Campaign" in resp.text


def test_campaign_detail_not_found():
    cid = uuid.uuid4()
    session = MagicMock()
    session.get.return_value = None

    with patch("src.dashboard.routes.detail.get_session",
               return_value=_mock_session(session)):
        resp = client.get(f"/campaigns/{cid}")

    assert resp.status_code == 404


def test_campaign_detail_run_buttons_present():
    cid = uuid.uuid4()
    session = _zero_counts_session(cid)

    with patch("src.dashboard.routes.detail.get_session",
               return_value=_mock_session(session)):
        with patch("src.dashboard.routes.detail.get_stage_counts",
                   return_value={
                       "total_hits": 0, "scraped": 0, "extracted": 0,
                       "verified_emails": 0, "total_leads": 0,
                       "pending_review": 0, "approved": 0,
                   }):
            resp = client.get(f"/campaigns/{cid}")

    assert resp.status_code == 200
    assert "Run ▶" in resp.text


# ---------------------------------------------------------------------------
# Pipeline run — concurrency guard
# ---------------------------------------------------------------------------


def test_run_stage_unknown_stage_returns_400():
    cid = uuid.uuid4()
    resp = client.post(f"/campaigns/{cid}/run/nonexistent")
    assert resp.status_code == 400


def test_run_stage_blocked_when_already_running():
    """When a task is already running, run buttons should appear disabled."""
    from datetime import datetime, timezone
    from unittest.mock import MagicMock, patch

    from src.dashboard.tasks import TaskEntry, registry

    cid = uuid.uuid4()

    # Inject a running task into registry
    running_task = MagicMock()
    running_task.done.return_value = False
    running_task.add_done_callback = MagicMock()

    old_tasks = dict(registry._tasks)
    registry._tasks[cid] = TaskEntry(
        stage="scrape",
        task=running_task,
        started_at=datetime.now(tz=timezone.utc),
    )

    try:
        with patch("src.dashboard.routes.pipeline.get_session",
                   return_value=_mock_session(_zero_counts_session(cid))):
            with patch("src.dashboard.routes.pipeline.get_stage_counts",
                       return_value={
                           "total_hits": 0, "scraped": 0, "extracted": 0,
                           "verified_emails": 0, "total_leads": 0,
                           "pending_review": 0, "approved": 0,
                       }):
                resp = client.post(f"/campaigns/{cid}/run/extract")
    finally:
        registry._tasks = old_tasks  # restore

    assert resp.status_code == 200
    assert "disabled" in resp.text


# ---------------------------------------------------------------------------
# Status polling endpoint
# ---------------------------------------------------------------------------


def test_status_returns_partial_html():
    cid = uuid.uuid4()

    with patch("src.dashboard.routes.status.get_session",
               return_value=_mock_session(_zero_counts_session(cid))):
        with patch("src.dashboard.routes.status.get_stage_counts",
                   return_value={
                       "total_hits": 5, "scraped": 3, "extracted": 2,
                       "verified_emails": 10, "total_leads": 2,
                       "pending_review": 1, "approved": 1,
                   }):
            resp = client.get(f"/campaigns/{cid}/status")

    assert resp.status_code == 200
    assert "Run ▶" in resp.text


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------


def test_review_queue_returns_200_empty():
    cid = uuid.uuid4()
    campaign = _make_campaign(cid)
    session = MagicMock()
    session.get.return_value = campaign

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    with patch("src.dashboard.routes.review.get_session",
               return_value=_mock_session(session)):
        resp = client.get(f"/campaigns/{cid}/review")

    assert resp.status_code == 200
    assert "No pending leads" in resp.text


def test_review_queue_not_found():
    cid = uuid.uuid4()
    session = MagicMock()
    session.get.return_value = None

    with patch("src.dashboard.routes.review.get_session",
               return_value=_mock_session(session)):
        resp = client.get(f"/campaigns/{cid}/review")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Review actions
# ---------------------------------------------------------------------------


def test_approve_action_returns_card_fragment():
    cid = uuid.uuid4()
    lid = uuid.uuid4()

    with patch("src.dashboard.routes.review.get_session",
               return_value=_mock_session(MagicMock())):
        with patch("src.dashboard.routes.review.approve_lead") as mock_approve:
            resp = client.post(f"/campaigns/{cid}/review/{lid}/approve")

    assert resp.status_code == 200
    assert "approved" in resp.text.lower()
    mock_approve.assert_called_once()


def test_reject_action_returns_card_fragment():
    cid = uuid.uuid4()
    lid = uuid.uuid4()

    with patch("src.dashboard.routes.review.get_session",
               return_value=_mock_session(MagicMock())):
        with patch("src.dashboard.routes.review.reject_lead") as mock_reject:
            resp = client.post(f"/campaigns/{cid}/review/{lid}/reject")

    assert resp.status_code == 200
    assert "rejected" in resp.text.lower()
    mock_reject.assert_called_once()


def test_needs_edit_action_returns_card_fragment():
    cid = uuid.uuid4()
    lid = uuid.uuid4()

    with patch("src.dashboard.routes.review.get_session",
               return_value=_mock_session(MagicMock())):
        with patch("src.dashboard.routes.review.mark_needs_edit") as mock_edit:
            resp = client.post(f"/campaigns/{cid}/review/{lid}/needs-edit")

    assert resp.status_code == 200
    assert "needs-edit" in resp.text.lower()
    mock_edit.assert_called_once()


# ---------------------------------------------------------------------------
# Export page
# ---------------------------------------------------------------------------


def test_export_page_returns_200():
    cid = uuid.uuid4()
    campaign = _make_campaign(cid)
    session = MagicMock()
    session.get.return_value = campaign
    session.scalar.return_value = 0

    with patch("src.dashboard.routes.export.get_session",
               return_value=_mock_session(session)):
        with patch("src.dashboard.routes.export._list_previous_exports", return_value=[]):
            resp = client.get(f"/campaigns/{cid}/export")

    assert resp.status_code == 200
    assert "Export" in resp.text


def test_export_page_not_found():
    cid = uuid.uuid4()
    session = MagicMock()
    session.get.return_value = None

    with patch("src.dashboard.routes.export.get_session",
               return_value=_mock_session(session)):
        resp = client.get(f"/campaigns/{cid}/export")

    assert resp.status_code == 404


def test_export_download_rejects_path_traversal():
    cid = uuid.uuid4()
    resp = client.get(f"/campaigns/{cid}/export/download?file=../../../etc/passwd")
    assert resp.status_code == 400


def test_export_download_rejects_missing_file():
    cid = uuid.uuid4()
    resp = client.get(f"/campaigns/{cid}/export/download?file=nonexistent.csv")
    assert resp.status_code == 404
