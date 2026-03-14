"""Tests for src/verification/website_checker.py"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.verification.website_checker import check_website


def _make_response(status_code: int) -> MagicMock:
    """Build a mock httpx.Response with the given status code."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = (200 <= status_code < 300)
    return resp


# ---------------------------------------------------------------------------
# HEAD 200 → True (no GET needed)
# ---------------------------------------------------------------------------


@patch("src.verification.website_checker.httpx.head")
def test_head_200_returns_true(mock_head):
    mock_head.return_value = _make_response(200)

    result = check_website("https://example.com")
    assert result is True
    mock_head.assert_called_once()


# ---------------------------------------------------------------------------
# HEAD 404 → falls back to GET; GET 200 → True
# ---------------------------------------------------------------------------


@patch("src.verification.website_checker.httpx.get")
@patch("src.verification.website_checker.httpx.head")
def test_head_404_get_200_returns_true(mock_head, mock_get):
    mock_head.return_value = _make_response(404)
    mock_get.return_value = _make_response(200)

    result = check_website("https://example.com")
    assert result is True
    mock_head.assert_called_once()
    mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# HEAD exception → falls back to GET; GET 200 → True
# ---------------------------------------------------------------------------


@patch("src.verification.website_checker.httpx.get")
@patch("src.verification.website_checker.httpx.head")
def test_head_exception_get_200_returns_true(mock_head, mock_get):
    mock_head.side_effect = httpx.ConnectError("refused")
    mock_get.return_value = _make_response(200)

    result = check_website("https://example.com")
    assert result is True


# ---------------------------------------------------------------------------
# HEAD exception → GET exception → False
# ---------------------------------------------------------------------------


@patch("src.verification.website_checker.httpx.get")
@patch("src.verification.website_checker.httpx.head")
def test_head_and_get_exception_returns_false(mock_head, mock_get):
    mock_head.side_effect = httpx.ConnectError("refused")
    mock_get.side_effect = httpx.ReadTimeout("timed out")

    result = check_website("https://example.com")
    assert result is False


# ---------------------------------------------------------------------------
# HEAD 200 with follow_redirects — check kwarg passed
# ---------------------------------------------------------------------------


@patch("src.verification.website_checker.httpx.head")
def test_head_follows_redirects(mock_head):
    mock_head.return_value = _make_response(200)

    check_website("https://example.com")
    _, kwargs = mock_head.call_args
    assert kwargs.get("follow_redirects") is True


# ---------------------------------------------------------------------------
# HEAD exception, GET 500 → False
# ---------------------------------------------------------------------------


@patch("src.verification.website_checker.httpx.get")
@patch("src.verification.website_checker.httpx.head")
def test_head_exception_get_500_returns_false(mock_head, mock_get):
    mock_head.side_effect = httpx.ConnectError("refused")
    mock_get.return_value = _make_response(500)

    result = check_website("https://example.com")
    assert result is False


# ---------------------------------------------------------------------------
# Timeout kwarg forwarded to both head and get
# ---------------------------------------------------------------------------


@patch("src.verification.website_checker.httpx.head")
def test_timeout_forwarded(mock_head):
    mock_head.return_value = _make_response(200)

    check_website("https://example.com", timeout=3.0)
    _, kwargs = mock_head.call_args
    assert kwargs.get("timeout") == 3.0


# ---------------------------------------------------------------------------
# GET 200 after HEAD 301 (non-2xx non-exception) → falls back
# ---------------------------------------------------------------------------


@patch("src.verification.website_checker.httpx.get")
@patch("src.verification.website_checker.httpx.head")
def test_head_301_get_200_returns_true(mock_head, mock_get):
    mock_head.return_value = _make_response(301)
    mock_get.return_value = _make_response(200)

    result = check_website("https://example.com")
    assert result is True
