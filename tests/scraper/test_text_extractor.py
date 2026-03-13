"""Unit tests for src/scraper/text_extractor.py."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.scraper.text_extractor import count_words, extract_text


# ---------------------------------------------------------------------------
# count_words
# ---------------------------------------------------------------------------


def test_count_words_basic():
    assert count_words("hello world") == 2


def test_count_words_empty_string():
    assert count_words("") == 0


def test_count_words_extra_whitespace():
    assert count_words("  hello   world  ") == 2


def test_count_words_single_word():
    assert count_words("dentist") == 1


# ---------------------------------------------------------------------------
# extract_text — trafilatura primary path
# ---------------------------------------------------------------------------


def test_extract_text_returns_empty_on_empty_html():
    assert extract_text("") == ""


def test_extract_text_uses_trafilatura_when_it_returns_content():
    html = "<html><body><p>Welcome to our dental practice.</p></body></html>"
    with patch("trafilatura.extract", return_value="Welcome to our dental practice.") as mock_t:
        result = extract_text(html)
    assert result == "Welcome to our dental practice."
    mock_t.assert_called_once()


def test_extract_text_falls_back_to_bs4_when_trafilatura_returns_none():
    html = "<html><body><p>Fallback content here.</p></body></html>"
    with patch("trafilatura.extract", return_value=None):
        result = extract_text(html)
    # BS4 fallback should still extract something
    assert "Fallback" in result or "fallback" in result.lower() or len(result) > 0


def test_extract_text_falls_back_to_bs4_when_trafilatura_raises():
    html = "<html><body><p>Error case content.</p></body></html>"
    with patch("trafilatura.extract", side_effect=RuntimeError("parse error")):
        result = extract_text(html)
    assert len(result) > 0


def test_extract_text_strips_scripts_via_bs4_fallback():
    html = """
    <html><head><script>alert('bad')</script></head>
    <body><p>Actual content.</p><script>more js</script></body></html>
    """
    with patch("trafilatura.extract", return_value=None):
        result = extract_text(html)
    assert "alert" not in result
    assert "Actual content" in result


# ---------------------------------------------------------------------------
# extract_text — integration: real trafilatura (if installed)
# ---------------------------------------------------------------------------


def test_extract_text_real_trafilatura_minimal():
    """Smoke test: real trafilatura extracts some text from a real HTML snippet."""
    html = """
    <html>
    <head><title>Smile Dental Practice</title></head>
    <body>
      <nav><a href="/">Home</a><a href="/about">About</a></nav>
      <main>
        <h1>Welcome to Smile Dental</h1>
        <p>We provide high-quality dental care in London.
        Our experienced team of dentists is here to help.</p>
      </main>
      <footer>Copyright 2024</footer>
    </body>
    </html>
    """
    result = extract_text(html)
    # Either trafilatura or BS4 should return something meaningful
    assert len(result) > 10
