"""Unit tests for src/enrichment/linkedin_lookup.py.

All tests mock ``httpx.post`` and ``time.sleep`` — no live DuckDuckGo calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.enrichment.linkedin_lookup import (
    LinkedInOwner,
    _extract_actual_url,
    _is_owner_title,
    _normalise_linkedin_url,
    _parse_from_snippet,
    _parse_from_title,
    _parse_linkedin_result,
    find_owner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_ddg_response(html: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = html
    return resp


# Minimal DuckDuckGo HTML fixture with one result.
def _ddg_html(title: str, href: str, snippet: str = "", display_url: str = "") -> str:
    return f"""
    <html><body>
      <div class="result">
        <a class="result__a" href="{href}">{title}</a>
        <span class="result__snippet">{snippet}</span>
        <span class="result__url">{display_url}</span>
      </div>
    </body></html>
    """


# ---------------------------------------------------------------------------
# _is_owner_title — word-boundary matching
# ---------------------------------------------------------------------------

class TestIsOwnerTitle:
    # Titles that SHOULD match
    @pytest.mark.parametrize("title", [
        "Owner",
        "owner",
        "Founder",
        "Co-Founder",
        "co-founder",
        "CEO",
        "ceo",
        "President",
        "Proprietor",
        "Chief Executive",
        "Managing Director",
        "Managing Partner",
    ])
    def test_matches_valid_owner_title(self, title: str):
        assert _is_owner_title(title) is True

    # Titles that MUST NOT match (regression guard for the bug fix)
    @pytest.mark.parametrize("title", [
        "Principal Engineer",
        "Principal Software Engineer",
        "Principal Consultant",
        "Machine Operator",
        "Forklift Operator",
        "Art Director",
        "Director of Photography",
        "Director of Marketing",
        "Creative Director",
        "Senior Director of Engineering",
    ])
    def test_rejects_non_owner_title(self, title: str):
        assert _is_owner_title(title) is False

    def test_case_insensitive(self):
        assert _is_owner_title("OWNER") is True
        assert _is_owner_title("Ceo") is True
        assert _is_owner_title("managing director") is True

    def test_empty_string_returns_false(self):
        assert _is_owner_title("") is False


# ---------------------------------------------------------------------------
# _parse_from_title — high-confidence path
# ---------------------------------------------------------------------------

class TestParseFromTitle:
    def test_extracts_name_and_title(self):
        result = _parse_from_title(
            "John Smith - Owner - ABC Plumbing | LinkedIn",
            "https://www.linkedin.com/in/john-smith",
        )
        assert result is not None
        assert result.full_name == "John Smith"
        assert result.first_name == "John"
        assert result.last_name == "Smith"
        assert result.title == "Owner"
        assert result.linkedin_url == "https://www.linkedin.com/in/john-smith"
        assert result.confidence == "high"

    def test_extracts_ceo_title(self):
        result = _parse_from_title(
            "Jane Doe - CEO - Waterproof Solutions | LinkedIn",
            "https://www.linkedin.com/in/jane-doe",
        )
        assert result is not None
        assert result.title == "CEO"
        assert result.confidence == "high"

    def test_extracts_founder_title(self):
        result = _parse_from_title(
            "Alice Wong - Founder - Wong Roofing Co | LinkedIn",
            "https://www.linkedin.com/in/alice-wong",
        )
        assert result is not None
        assert result.full_name == "Alice Wong"
        assert result.title == "Founder"

    def test_returns_none_for_non_owner_title(self):
        """LinkedIn titles with non-owner roles must be rejected."""
        result = _parse_from_title(
            "Bob Jones - Principal Engineer - Big Tech | LinkedIn",
            "https://www.linkedin.com/in/bob-jones",
        )
        assert result is None

    def test_returns_none_for_art_director(self):
        result = _parse_from_title(
            "Carol White - Art Director - Creative Agency | LinkedIn",
            "https://www.linkedin.com/in/carol-white",
        )
        assert result is None

    def test_returns_none_when_only_name_and_linkedin(self):
        """Title with only name and no role segment returns None."""
        result = _parse_from_title(
            "John Smith | LinkedIn",
            "https://www.linkedin.com/in/john-smith",
        )
        assert result is None

    def test_strips_linkedin_suffix_before_parsing(self):
        """The ' | LinkedIn' suffix must be stripped before splitting on '-'."""
        result = _parse_from_title(
            "Mark Lee - President - Lee Waterproofing | LinkedIn",
            "https://www.linkedin.com/in/mark-lee",
        )
        assert result is not None
        assert result.title == "President"


# ---------------------------------------------------------------------------
# _parse_from_snippet — medium-confidence path
# ---------------------------------------------------------------------------

class TestParseFromSnippet:
    def test_extracts_owner_from_snippet(self):
        result = _parse_from_snippet(
            "John Smith · Owner at ABC Plumbing · Chicago area",
            "https://www.linkedin.com/in/john-smith",
        )
        assert result is not None
        assert result.full_name == "John Smith"
        assert result.title == "Owner"
        assert result.confidence == "medium"

    def test_extracts_founder_from_snippet(self):
        result = _parse_from_snippet(
            "Sara Jones · Founder at Jones Roofing · Greater Boston area",
            "https://www.linkedin.com/in/sara-jones",
        )
        assert result is not None
        assert result.title == "Founder"

    def test_returns_none_for_non_owner_snippet(self):
        result = _parse_from_snippet(
            "Tom Brown · Principal Engineer at Acme Corp",
            "https://www.linkedin.com/in/tom-brown",
        )
        assert result is None

    def test_returns_none_when_no_pattern_match(self):
        result = _parse_from_snippet(
            "General text with no LinkedIn snippet pattern here.",
            "https://www.linkedin.com/in/someone",
        )
        assert result is None


# ---------------------------------------------------------------------------
# _normalise_linkedin_url
# ---------------------------------------------------------------------------

class TestNormaliseLinkedInUrl:
    def test_returns_clean_https_url_from_direct_link(self):
        """`_normalise_linkedin_url` receives an already-decoded URL from _extract_actual_url."""
        result = _normalise_linkedin_url("https://www.linkedin.com/in/john-smith")
        assert result == "https://www.linkedin.com/in/john-smith"

    def test_strips_query_params(self):
        """URLs with tracking/UTM params are normalised to bare profile URL."""
        result = _normalise_linkedin_url(
            "https://www.linkedin.com/in/john-smith?utm_source=duckduckgo&trk=public_profile"
        )
        assert result == "https://www.linkedin.com/in/john-smith"

    def test_handles_direct_linkedin_url(self):
        result = _normalise_linkedin_url("https://www.linkedin.com/in/jane-doe-123")
        assert result == "https://www.linkedin.com/in/jane-doe-123"

    def test_strips_trailing_slash(self):
        result = _normalise_linkedin_url("https://www.linkedin.com/in/john-smith/")
        assert result == "https://www.linkedin.com/in/john-smith"

    def test_returns_none_for_non_linkedin_url(self):
        result = _normalise_linkedin_url("https://www.example.com/profile/john")
        assert result is None

    def test_returns_none_for_empty_string(self):
        result = _normalise_linkedin_url("")
        assert result is None

    def test_extract_actual_url_decodes_ddg_redirect(self):
        """_extract_actual_url decodes DDG's percent-encoded redirect wrapper.

        In production: _ddg_search calls _extract_actual_url(href) before
        _normalise_linkedin_url ever sees the URL.  This test verifies the
        decoding step produces a clean LinkedIn URL.
        """
        encoded = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.linkedin.com%2Fin%2Fjohn-smith"
        decoded = _extract_actual_url(encoded)
        assert decoded == "https://www.linkedin.com/in/john-smith"
        # Now normalisation works on the decoded URL
        normalised = _normalise_linkedin_url(decoded)
        assert normalised == "https://www.linkedin.com/in/john-smith"


# ---------------------------------------------------------------------------
# _parse_linkedin_result — integration of title + snippet paths
# ---------------------------------------------------------------------------

class TestParseLinkedInResult:
    def test_returns_none_for_non_linkedin_url(self):
        result = _parse_linkedin_result({
            "url": "https://www.example.com/profile/john",
            "title": "John Smith - Owner - ABC",
            "snippet": "",
        })
        assert result is None

    def test_uses_title_when_available(self):
        result = _parse_linkedin_result({
            "url": "https://www.linkedin.com/in/john-smith",
            "title": "John Smith - Owner - ABC Plumbing | LinkedIn",
            "snippet": "Some snippet text",
        })
        assert result is not None
        assert result.confidence == "high"

    def test_falls_back_to_snippet(self):
        result = _parse_linkedin_result({
            "url": "https://www.linkedin.com/in/john-smith",
            "title": "John Smith | LinkedIn",  # no role in title
            "snippet": "John Smith · Owner at ABC Plumbing · Chicago",
        })
        assert result is not None
        assert result.confidence == "medium"


# ---------------------------------------------------------------------------
# find_owner — integration + fallback gate
# ---------------------------------------------------------------------------

class TestFindOwner:
    def test_returns_none_on_empty_ddg_results(self):
        empty_html = "<html><body></body></html>"
        mock_resp = _mock_ddg_response(empty_html)

        with patch("httpx.post", return_value=mock_resp), \
             patch("time.sleep"):
            result = find_owner("ABC Plumbing", "Chicago", delay=0.0)

        assert result is None

    def test_returns_none_on_ddg_error(self):
        import httpx
        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")), \
             patch("time.sleep"):
            result = find_owner("ABC Plumbing", "Chicago", delay=0.0)

        assert result is None

    def test_fallback_query_NOT_run_when_disabled(self):
        """When city_fallback=False (default), only ONE DDG request is made."""
        empty_html = "<html><body></body></html>"
        mock_resp = _mock_ddg_response(empty_html)

        with patch("httpx.post", return_value=mock_resp) as mock_post, \
             patch("time.sleep"):
            find_owner("ABC Plumbing", "Chicago", delay=0.0, city_fallback=False)

        # Exactly one DDG request — the city-scoped query. No fallback.
        assert mock_post.call_count == 1

    def test_fallback_query_IS_run_when_enabled(self):
        """When city_fallback=True and primary returns nothing, a second request fires."""
        empty_html = "<html><body></body></html>"
        mock_resp = _mock_ddg_response(empty_html)

        with patch("httpx.post", return_value=mock_resp) as mock_post, \
             patch("time.sleep"):
            find_owner("ABC Plumbing", "Chicago", delay=0.0, city_fallback=True)

        # Two requests: primary (with city) + fallback (without city).
        assert mock_post.call_count == 2

    def test_returns_owner_when_found_in_title(self):
        html = _ddg_html(
            title="John Smith - Owner - ABC Plumbing | LinkedIn",
            href="https://www.linkedin.com/in/john-smith",
            snippet="",
        )
        mock_resp = _mock_ddg_response(html)

        with patch("httpx.post", return_value=mock_resp), \
             patch("time.sleep"):
            result = find_owner("ABC Plumbing", "Chicago", delay=0.0)

        assert result is not None
        assert result.full_name == "John Smith"
        assert result.confidence == "high"

    def test_returns_none_when_no_result_has_owner_title(self):
        """All results are non-owner roles → returns None."""
        html = _ddg_html(
            title="Bob Jones - Principal Engineer - ABC Corp | LinkedIn",
            href="https://www.linkedin.com/in/bob-jones",
            snippet="",
        )
        mock_resp = _mock_ddg_response(html)

        with patch("httpx.post", return_value=mock_resp), \
             patch("time.sleep"):
            result = find_owner("ABC Corp", "Chicago", delay=0.0)

        assert result is None
