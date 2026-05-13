"""Unit tests for src/discovery/yelp.py.

All tests mock ``httpx.get`` and ``time.sleep`` — no live network calls.
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.discovery.yelp import YelpClient


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_client() -> YelpClient:
    return YelpClient(api_key="test-key", rate_limit_delay=0.0, max_results=50)


def _mock_response(status: int = 200, json_data: Optional[dict] = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.text = ""
    return resp


# A minimal, valid Yelp business search result dict.
_BIZ_STUB: dict = {
    "id": "abc-plumbing-chicago",
    "name": "ABC Plumbing",
    "phone": "+13125550100",
    "rating": 4.2,
    "review_count": 87,
    "is_closed": False,
    "coordinates": {"latitude": 41.8827, "longitude": -87.6233},
    "location": {
        "address1": "123 Main St",
        "address2": "",
        "city": "Chicago",
        "state": "IL",
        "zip_code": "60601",
        "country": "US",
    },
    "categories": [{"alias": "plumbing", "title": "Plumbing"}],
}


# ---------------------------------------------------------------------------
# _parse_business
# ---------------------------------------------------------------------------

class TestParseBusiness:
    def test_maps_core_fields(self):
        client = _make_client()
        result = client._parse_business(_BIZ_STUB)

        assert result is not None
        assert result.name == "ABC Plumbing"
        assert result.place_id == "yelp:abc-plumbing-chicago"
        assert result.city == "Chicago"
        assert result.state == "IL"
        assert result.postal_code == "60601"
        assert result.country_code == "US"
        assert result.phone_number == "+13125550100"
        assert result.rating == 4.2
        assert result.user_rating_count == 87
        assert result.latitude == pytest.approx(41.8827)
        assert result.longitude == pytest.approx(-87.6233)

    def test_operational_status_when_not_closed(self):
        client = _make_client()
        result = client._parse_business({**_BIZ_STUB, "is_closed": False})
        assert result.business_status == "OPERATIONAL"

    def test_closed_status_when_is_closed_true(self):
        client = _make_client()
        result = client._parse_business({**_BIZ_STUB, "is_closed": True})
        assert result.business_status == "CLOSED"

    def test_categories_mapped_to_types(self):
        client = _make_client()
        result = client._parse_business(_BIZ_STUB)
        assert "Plumbing" in result.types

    def test_place_id_has_yelp_prefix(self):
        """Ensures Yelp IDs never collide with Google Place IDs."""
        client = _make_client()
        result = client._parse_business(_BIZ_STUB)
        assert result.place_id.startswith("yelp:")

    def test_website_uri_is_none_after_parse(self):
        """website_uri is filled later by _fetch_website; parse returns None."""
        client = _make_client()
        result = client._parse_business(_BIZ_STUB)
        assert result.website_uri is None

    def test_returns_none_when_id_missing(self):
        client = _make_client()
        biz = {k: v for k, v in _BIZ_STUB.items() if k != "id"}
        assert client._parse_business(biz) is None

    def test_returns_none_when_name_missing(self):
        client = _make_client()
        biz = {k: v for k, v in _BIZ_STUB.items() if k != "name"}
        assert client._parse_business(biz) is None

    def test_returns_none_when_id_empty(self):
        client = _make_client()
        assert client._parse_business({**_BIZ_STUB, "id": ""}) is None

    def test_handles_missing_optional_fields_gracefully(self):
        """Sparse response (only id + name) should not raise."""
        client = _make_client()
        result = client._parse_business({"id": "x", "name": "Minimal Biz"})
        assert result is not None
        assert result.city is None
        assert result.phone_number is None
        assert result.rating is None


# ---------------------------------------------------------------------------
# _fetch_website  (THE CRITICAL BUG FIX)
# ---------------------------------------------------------------------------

class TestFetchWebsite:
    def test_returns_business_website_when_present(self):
        """The ``website`` field from Yelp details response is returned."""
        client = _make_client()
        detail_data = {
            "id": "abc-plumbing-chicago",
            "url": "https://www.yelp.com/biz/abc-plumbing-chicago",  # listing URL — must be ignored
            "website": "https://www.abcplumbing.com/",               # real website — must be returned
        }
        mock_resp = _mock_response(200, detail_data)

        with patch("httpx.get", return_value=mock_resp), \
             patch("time.sleep"):
            result = client._fetch_website("abc-plumbing-chicago")

        assert result == "https://www.abcplumbing.com/"

    def test_returns_none_when_website_field_absent(self):
        """When the business has no website on Yelp, return None (not the listing URL)."""
        client = _make_client()
        detail_data = {
            "id": "abc-plumbing-chicago",
            "url": "https://www.yelp.com/biz/abc-plumbing-chicago",
            # No ``website`` key
        }
        mock_resp = _mock_response(200, detail_data)

        with patch("httpx.get", return_value=mock_resp), \
             patch("time.sleep"):
            result = client._fetch_website("abc-plumbing-chicago")

        assert result is None

    def test_returns_none_when_website_field_empty_string(self):
        """Empty string in ``website`` is treated as absent."""
        client = _make_client()
        detail_data = {
            "id": "abc-plumbing-chicago",
            "url": "https://www.yelp.com/biz/abc-plumbing-chicago",
            "website": "",
        }
        mock_resp = _mock_response(200, detail_data)

        with patch("httpx.get", return_value=mock_resp), \
             patch("time.sleep"):
            result = client._fetch_website("abc-plumbing-chicago")

        assert result is None

    def test_never_returns_yelp_listing_url(self):
        """Regression: Yelp listing URL must never be returned as the website."""
        client = _make_client()
        detail_data = {
            "url": "https://www.yelp.com/biz/some-business",
            # No ``website`` key — listing URL only
        }
        mock_resp = _mock_response(200, detail_data)

        with patch("httpx.get", return_value=mock_resp), \
             patch("time.sleep"):
            result = client._fetch_website("some-business")

        assert result is None
        # Belt-and-suspenders: if something were returned, it must not be yelp.com
        if result is not None:
            assert "yelp.com" not in result

    def test_returns_none_on_non_200_status(self):
        client = _make_client()
        mock_resp = _mock_response(404)

        with patch("httpx.get", return_value=mock_resp), \
             patch("time.sleep"):
            result = client._fetch_website("missing-biz")

        assert result is None

    def test_returns_none_on_http_error(self):
        import httpx
        client = _make_client()

        with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")), \
             patch("time.sleep"):
            result = client._fetch_website("any-id")

        assert result is None


# ---------------------------------------------------------------------------
# _search — respects max_results
# ---------------------------------------------------------------------------

class TestSearchMaxResults:
    def test_stops_after_max_results(self):
        """_search should not request more results than max_results."""
        client = YelpClient(api_key="test-key", rate_limit_delay=0.0, max_results=3)

        # First page has 3 results, total=50 — client should stop after one page.
        search_data = {
            "businesses": [_BIZ_STUB, _BIZ_STUB, _BIZ_STUB],
            "total": 50,
        }
        detail_data: dict = {}  # no website field → _fetch_website returns None

        search_resp = _mock_response(200, search_data)
        detail_resp = _mock_response(200, detail_data)

        with patch("httpx.get", side_effect=[search_resp] + [detail_resp] * 3), \
             patch("time.sleep"):
            results = client._search("plumber", location="Chicago, US")

        # Should not exceed 3 even though Yelp says total=50
        assert len(results) <= 3

    def test_stops_on_empty_page(self):
        """If businesses list is empty on first page, loop exits immediately."""
        client = _make_client()
        search_data = {"businesses": [], "total": 0}
        search_resp = _mock_response(200, search_data)

        with patch("httpx.get", return_value=search_resp), \
             patch("time.sleep"):
            results = client._search("plumber", location="Chicago, US")

        assert results == []

    def test_stops_on_429(self):
        """Rate limit response terminates pagination without raising."""
        client = _make_client()
        rate_limit_resp = _mock_response(429)

        with patch("httpx.get", return_value=rate_limit_resp), \
             patch("time.sleep"):
            results = client._search("plumber", location="Chicago, US")

        assert results == []

    def test_domain_extracted_from_website(self):
        """When _fetch_website returns a URL, domain is set on PlaceResult."""
        client = YelpClient(api_key="test-key", rate_limit_delay=0.0, max_results=1)

        search_data = {"businesses": [_BIZ_STUB], "total": 1}
        detail_data = {"website": "https://www.abcplumbing.com/"}

        search_resp = _mock_response(200, search_data)
        detail_resp = _mock_response(200, detail_data)

        with patch("httpx.get", side_effect=[search_resp, detail_resp]), \
             patch("time.sleep"):
            results = client._search("plumber", location="Chicago, US")

        assert len(results) == 1
        assert results[0].website_uri == "https://www.abcplumbing.com/"
        assert results[0].domain is not None
        assert "yelp" not in (results[0].domain or "")

    def test_domain_is_none_when_no_website(self):
        """When _fetch_website returns None, domain stays None (no yelp.com contamination)."""
        client = YelpClient(api_key="test-key", rate_limit_delay=0.0, max_results=1)

        search_data = {"businesses": [_BIZ_STUB], "total": 1}
        detail_data = {"url": "https://www.yelp.com/biz/abc-plumbing-chicago"}  # no ``website``

        search_resp = _mock_response(200, search_data)
        detail_resp = _mock_response(200, detail_data)

        with patch("httpx.get", side_effect=[search_resp, detail_resp]), \
             patch("time.sleep"):
            results = client._search("plumber", location="Chicago, US")

        assert len(results) == 1
        # website_uri must NOT be a yelp.com URL
        uri = results[0].website_uri
        if uri is not None:
            assert "yelp.com" not in uri
        # domain must NOT be yelp.com
        assert results[0].domain != "www.yelp.com"
        assert results[0].domain != "yelp.com"
