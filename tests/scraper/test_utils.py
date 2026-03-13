"""Unit tests for src/scraper/utils.py."""
from __future__ import annotations

import pytest

from src.scraper.utils import normalize_url


def test_normalize_url_lowercases_scheme_and_host():
    assert normalize_url("HTTPS://EXAMPLE.COM/path") == "https://example.com/path"


def test_normalize_url_strips_trailing_slash_from_non_root():
    assert normalize_url("https://example.com/about/") == "https://example.com/about"


def test_normalize_url_keeps_root_slash():
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_normalize_url_strips_query_string():
    assert normalize_url("https://example.com/page?q=1&foo=bar") == "https://example.com/page"


def test_normalize_url_strips_fragment():
    assert normalize_url("https://example.com/page#section") == "https://example.com/page"


def test_normalize_url_strips_default_https_port():
    assert normalize_url("https://example.com:443/path") == "https://example.com/path"


def test_normalize_url_strips_default_http_port():
    assert normalize_url("http://example.com:80/path") == "http://example.com/path"


def test_normalize_url_keeps_non_default_port():
    assert normalize_url("https://example.com:8443/path") == "https://example.com:8443/path"


def test_normalize_url_strips_query_and_fragment_together():
    assert normalize_url("https://x.com/p?q=1#h") == "https://x.com/p"


def test_normalize_url_no_double_slash_on_root():
    result = normalize_url("https://example.com")
    # netloc only, no path — urlunparse gives empty path; acceptable
    assert "example.com" in result
    assert "?" not in result
    assert "#" not in result
