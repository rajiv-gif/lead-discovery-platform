"""Tests for src/extraction/llm.py — call_llm with mocked LLMClient."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.extraction.llm import call_llm, _parse_response
from src.extraction.models import ExtractionResult
from src.models.enums import PageType


def _make_page(text: str = "Some page text") -> MagicMock:
    page = MagicMock()
    page.extracted_text = text
    page.page_type = PageType.TEAM
    page.company_id = uuid.uuid4()
    page.id = uuid.uuid4()
    return page


def _make_client(response: str) -> MagicMock:
    client = MagicMock()
    client.complete.return_value = response
    return client


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_valid_contacts():
    raw = json.dumps({
        "contacts": [{"full_name": "Dr. Alice Smith", "title": "Dentist", "email": None, "phone": None}],
        "company_emails": [],
        "company_phones": [],
    })
    result = _parse_response(raw)
    assert len(result.contacts) == 1
    assert result.contacts[0].full_name == "Dr. Alice Smith"
    assert result.contacts[0].title == "Dentist"


def test_parse_valid_company_emails():
    raw = json.dumps({
        "contacts": [],
        "company_emails": ["info@clinic.com", "hello@clinic.com"],
        "company_phones": [],
    })
    result = _parse_response(raw)
    assert len(result.emails) == 2
    assert all(e.is_generic for e in result.emails)
    assert result.emails[0].address == "info@clinic.com"


def test_parse_valid_company_phones():
    raw = json.dumps({
        "contacts": [],
        "company_emails": [],
        "company_phones": ["+442071234567"],
    })
    result = _parse_response(raw)
    assert len(result.phones) == 1
    assert result.phones[0].e164 == "+442071234567"


def test_parse_empty_arrays():
    raw = json.dumps({"contacts": [], "company_emails": [], "company_phones": []})
    result = _parse_response(raw)
    assert result.contacts == []
    assert result.emails == []
    assert result.phones == []


# ---------------------------------------------------------------------------
# call_llm — success cases
# ---------------------------------------------------------------------------


def test_call_llm_returns_extraction_result(tmp_path):
    raw = json.dumps({
        "contacts": [{"full_name": "Dr. Bob Jones", "title": "Orthodontist", "email": None, "phone": None}],
        "company_emails": ["info@clinic.com"],
        "company_phones": [],
    })
    client = _make_client(raw)
    page = _make_page()

    result = call_llm(client, page, "Test Clinic", tmp_path)

    assert result is not None
    assert len(result.contacts) == 1
    assert result.contacts[0].full_name == "Dr. Bob Jones"
    assert len(result.emails) == 1


def test_call_llm_writes_artifact_on_success(tmp_path):
    raw = json.dumps({"contacts": [], "company_emails": [], "company_phones": []})
    client = _make_client(raw)
    page = _make_page()

    call_llm(client, page, "Test Clinic", tmp_path)

    artifacts = list(tmp_path.glob("*.json"))
    assert len(artifacts) == 1
    data = json.loads(artifacts[0].read_text())
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# call_llm — malformed JSON
# ---------------------------------------------------------------------------


def test_call_llm_malformed_json_returns_none(tmp_path):
    client = _make_client("this is not json {{{")
    page = _make_page()

    result = call_llm(client, page, "Test Clinic", tmp_path)

    assert result is None
    artifacts = list(tmp_path.glob("*.json"))
    assert len(artifacts) == 1
    data = json.loads(artifacts[0].read_text())
    assert data["status"] == "malformed"
    assert "error" in data


# ---------------------------------------------------------------------------
# call_llm — API exception
# ---------------------------------------------------------------------------


def test_call_llm_api_exception_returns_none(tmp_path):
    client = MagicMock()
    client.complete.side_effect = Exception("Network timeout")
    page = _make_page()

    result = call_llm(client, page, "Test Clinic", tmp_path)

    assert result is None
    artifacts = list(tmp_path.glob("*.json"))
    assert len(artifacts) == 1
    data = json.loads(artifacts[0].read_text())
    assert data["status"] == "error"
    assert "Network timeout" in data["error"]


# ---------------------------------------------------------------------------
# Artifact always written
# ---------------------------------------------------------------------------


def test_call_llm_artifact_written_in_all_cases(tmp_path):
    """Artifact file is created whether success, malformed, or error."""
    cases = [
        json.dumps({"contacts": [], "company_emails": [], "company_phones": []}),  # success
        "INVALID JSON",  # malformed
    ]
    for i, response in enumerate(cases):
        subdir = tmp_path / str(i)
        subdir.mkdir()
        client = _make_client(response)
        call_llm(client, _make_page(), "Clinic", subdir)
        assert len(list(subdir.glob("*.json"))) == 1
