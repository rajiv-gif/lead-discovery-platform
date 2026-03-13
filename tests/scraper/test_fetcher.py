"""Unit tests for src/scraper/fetcher.py.

All tests mock httpx.get and urllib.robotparser — no live network calls.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.scraper.fetcher import DomainRateLimiter, Fetcher, FetchResult, RobotCache


# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------


def test_fetch_result_ok_for_200():
    r = FetchResult(url="http://x.com", final_url="http://x.com", html="<html/>", status_code=200)
    assert r.ok is True


def test_fetch_result_not_ok_for_404():
    r = FetchResult(url="http://x.com", final_url="http://x.com", html="", status_code=404)
    assert r.ok is False


def test_fetch_result_not_ok_when_status_none():
    r = FetchResult(url="http://x.com", final_url="http://x.com", html="", status_code=None)
    assert r.ok is False


def test_fetch_result_content_hash_sha256():
    r = FetchResult(url="http://x.com", final_url="http://x.com", html="hello", status_code=200)
    import hashlib
    expected = hashlib.sha256(b"hello").hexdigest()
    assert r.content_hash == expected


def test_fetch_result_content_hash_none_when_empty_html():
    r = FetchResult(url="http://x.com", final_url="http://x.com", html="", status_code=200)
    assert r.content_hash is None


# ---------------------------------------------------------------------------
# RobotCache — fail-open
# ---------------------------------------------------------------------------


def test_robot_cache_allows_when_robots_txt_fetch_fails():
    """Network errors fetching robots.txt must be treated as allow-all."""
    cache = RobotCache()
    with patch("urllib.robotparser.RobotFileParser.read", side_effect=OSError("timeout")):
        assert cache.is_allowed("http://example.com/page") is True


def test_robot_cache_logs_warning_on_failure(caplog):
    cache = RobotCache()
    with patch("urllib.robotparser.RobotFileParser.read", side_effect=OSError("network error")):
        import logging
        with caplog.at_level(logging.WARNING, logger="src.scraper.fetcher"):
            result = cache.is_allowed("http://example.com/page")
    assert result is True
    assert any("robots.txt" in rec.message for rec in caplog.records)


def test_robot_cache_respects_disallow():
    """If robots.txt explicitly disallows a path, return False."""
    cache = RobotCache()

    def fake_read(self):
        self.parse(["User-agent: *", "Disallow: /private/"])

    with patch("urllib.robotparser.RobotFileParser.read", fake_read):
        assert cache.is_allowed("http://example.com/private/page") is False


def test_robot_cache_caches_per_domain():
    """robots.txt is fetched only once per domain."""
    cache = RobotCache()

    read_count = [0]

    def counting_read(self):
        read_count[0] += 1
        self.parse(["User-agent: *", "Allow: /"])

    with patch("urllib.robotparser.RobotFileParser.read", counting_read):
        cache.is_allowed("http://example.com/page1")
        cache.is_allowed("http://example.com/page2")

    assert read_count[0] == 1  # cached after first call


# ---------------------------------------------------------------------------
# DomainRateLimiter
# ---------------------------------------------------------------------------


def test_rate_limiter_sleeps_between_requests():
    limiter = DomainRateLimiter(delay_seconds=0.05)
    limiter.wait("http://example.com/a")  # first call — no sleep needed

    with patch("time.sleep") as mock_sleep:
        limiter.wait("http://example.com/b")
        # Sleep was called (remaining > 0 because < 0.05s elapsed)
        mock_sleep.assert_called_once()
        sleep_duration = mock_sleep.call_args[0][0]
        assert 0 < sleep_duration <= 0.05


def test_rate_limiter_no_sleep_after_delay_elapsed():
    limiter = DomainRateLimiter(delay_seconds=0.01)
    limiter._last_fetch["example.com"] = time.monotonic() - 1.0  # simulate old fetch

    with patch("time.sleep") as mock_sleep:
        limiter.wait("http://example.com/page")
        mock_sleep.assert_not_called()


def test_rate_limiter_separate_domains_do_not_interact():
    limiter = DomainRateLimiter(delay_seconds=0.5)
    limiter.wait("http://site-a.com/page")

    with patch("time.sleep") as mock_sleep:
        limiter.wait("http://site-b.com/page")
        mock_sleep.assert_not_called()  # different domain, no wait needed


# ---------------------------------------------------------------------------
# Fetcher.fetch
# ---------------------------------------------------------------------------


def _make_fetcher(**kwargs) -> Fetcher:
    """Return a Fetcher with zero delays and a permissive robot cache."""
    robot_cache = RobotCache()
    with patch("urllib.robotparser.RobotFileParser.read"):
        pass
    robot_cache._cache["example.com"] = _allow_all_parser()
    return Fetcher(rate_limit_delay=0.0, connect_timeout=5.0, read_timeout=5.0,
                   robot_cache=robot_cache, **kwargs)


def _allow_all_parser():
    from urllib.robotparser import RobotFileParser
    p = RobotFileParser()
    p.parse(["User-agent: *", "Allow: /"])
    return p


def _mock_response(status=200, text="<html>body</html>", url="http://example.com/"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.url = url
    resp.headers = {"content-type": "text/html; charset=utf-8"}
    return resp


@patch("httpx.get")
def test_fetcher_returns_ok_result_on_200(mock_get):
    mock_get.return_value = _mock_response(status=200, text="<html>hello</html>")
    fetcher = _make_fetcher()
    result = fetcher.fetch("http://example.com/")
    assert result.ok is True
    assert result.html == "<html>hello</html>"
    assert result.status_code == 200


@patch("httpx.get")
def test_fetcher_returns_error_result_on_404(mock_get):
    mock_get.return_value = _mock_response(status=404, text="")
    fetcher = _make_fetcher()
    result = fetcher.fetch("http://example.com/missing")
    assert result.ok is False
    assert result.status_code == 404
    assert result.error is not None


@patch("httpx.get")
def test_fetcher_captures_network_error(mock_get):
    mock_get.side_effect = httpx.ConnectError("refused")
    fetcher = _make_fetcher()
    result = fetcher.fetch("http://example.com/")
    assert result.ok is False
    assert result.status_code is None
    assert "refused" in (result.error or "")


@patch("httpx.get")
def test_fetcher_returns_disallowed_when_robots_blocks(mock_get):
    disallow_parser = _allow_all_parser()
    from unittest.mock import patch as _patch
    with _patch.object(disallow_parser, "can_fetch", return_value=False):
        robot_cache = RobotCache()
        robot_cache._cache["example.com"] = disallow_parser
        fetcher = Fetcher(rate_limit_delay=0.0, robot_cache=robot_cache)
        result = fetcher.fetch("http://example.com/private")
    assert result.ok is False
    assert result.error == "disallowed by robots.txt"
    mock_get.assert_not_called()


@patch("httpx.get")
def test_fetcher_content_type_passed_through(mock_get):
    resp = _mock_response()
    resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_get.return_value = resp
    fetcher = _make_fetcher()
    result = fetcher.fetch("http://example.com/")
    assert result.content_type == "text/html; charset=utf-8"


@patch("httpx.get")
def test_fetcher_follows_redirect_and_records_final_url(mock_get):
    resp = _mock_response(url="http://example.com/canonical/")
    mock_get.return_value = resp
    fetcher = _make_fetcher()
    result = fetcher.fetch("http://example.com/old-path")
    assert result.final_url == "http://example.com/canonical/"
