"""Unit tests for src/discovery/places.py.

All tests mock ``httpx.post`` and ``time.sleep`` — no live API calls.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from src.discovery.places import PlacesAPIError, PlacesClient, PlaceResult
from src.discovery.strategies import GeoQuery


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

FULL_PLACE_RAW: dict = {
    "id": "ChIJabc123",
    "displayName": {"text": "Smile Dental Practice", "languageCode": "en"},
    "formattedAddress": "123 High St, London, SW1A 1AA, UK",
    "websiteUri": "https://www.smiledental.co.uk/",
    "internationalPhoneNumber": "+44 20 7946 0958",
    "rating": 4.7,
    "userRatingCount": 312,
    "location": {"latitude": 51.5074, "longitude": -0.1278},
    "businessStatus": "OPERATIONAL",
    "types": ["dentist", "health", "establishment"],
    "addressComponents": [
        {"longText": "123", "shortText": "123", "types": ["street_number"]},
        {"longText": "High Street", "shortText": "High St", "types": ["route"]},
        {"longText": "London", "shortText": "London", "types": ["locality", "political"]},
        {
            "longText": "Greater London",
            "shortText": "GL",
            "types": ["administrative_area_level_1", "political"],
        },
        {
            "longText": "United Kingdom",
            "shortText": "GB",
            "types": ["country", "political"],
        },
        {"longText": "SW1A 1AA", "shortText": "SW1A 1AA", "types": ["postal_code"]},
    ],
}


def _make_client(**kwargs) -> PlacesClient:
    defaults = {"api_key": "test-api-key", "rate_limit_delay": 0.0, "max_pages": 3}
    defaults.update(kwargs)
    return PlacesClient(**defaults)


def _make_response(places: list[dict], next_token: str | None = None):
    """Build a mock httpx.Response for Places API."""
    body: dict = {"places": places}
    if next_token:
        body["nextPageToken"] = next_token
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = body
    mock.text = json.dumps(body)
    return mock


def _city_query() -> GeoQuery:
    return GeoQuery(
        text_query="dentists in London, UK",
        location_restriction=None,
        method="city",
        center_lat=None,
        center_lng=None,
        radius_m=None,
    )


# ---------------------------------------------------------------------------
# _parse_place
# ---------------------------------------------------------------------------


def test_parse_place_full_response():
    client = _make_client()
    result = client._parse_place(FULL_PLACE_RAW, rank=0)

    assert result.place_id == "ChIJabc123"
    assert result.name == "Smile Dental Practice"
    assert result.domain == "www.smiledental.co.uk"
    assert result.phone_number == "+44 20 7946 0958"
    assert result.rating == 4.7
    assert result.user_rating_count == 312
    assert result.latitude == pytest.approx(51.5074)
    assert result.longitude == pytest.approx(-0.1278)
    assert result.city == "London"
    assert result.state == "Greater London"
    assert result.country == "United Kingdom"
    assert result.country_code == "GB"
    assert result.postal_code == "SW1A 1AA"
    assert result.business_status == "OPERATIONAL"
    assert "dentist" in result.types
    assert result.raw == FULL_PLACE_RAW


def test_parse_place_missing_optional_fields():
    minimal = {"id": "ChIJxyz", "displayName": {"text": "Basic Dental"}}
    client = _make_client()
    result = client._parse_place(minimal, rank=0)

    assert result.place_id == "ChIJxyz"
    assert result.name == "Basic Dental"
    assert result.domain is None
    assert result.phone_number is None
    assert result.rating is None
    assert result.city is None
    assert result.country is None
    assert result.types == []


def test_parse_place_extracts_domain():
    raw = dict(FULL_PLACE_RAW)
    raw["websiteUri"] = "https://www.example-dental.co.uk/about"
    result = _make_client()._parse_place(raw, rank=0)
    assert result.domain == "www.example-dental.co.uk"


def test_parse_place_no_website_domain_is_none():
    raw = {k: v for k, v in FULL_PLACE_RAW.items() if k != "websiteUri"}
    result = _make_client()._parse_place(raw, rank=0)
    assert result.domain is None
    assert result.website_uri is None


# ---------------------------------------------------------------------------
# _extract_domain
# ---------------------------------------------------------------------------


def test_extract_domain_returns_none_for_none():
    assert PlacesClient._extract_domain(None) is None


def test_extract_domain_returns_none_for_empty():
    assert PlacesClient._extract_domain("") is None


def test_extract_domain_strips_path():
    assert PlacesClient._extract_domain("https://example.com/page?x=1") == "example.com"


# ---------------------------------------------------------------------------
# search — pagination and page count
# ---------------------------------------------------------------------------


@patch("time.sleep")
@patch("httpx.post")
def test_search_single_page_no_next_token(mock_post, mock_sleep):
    mock_post.return_value = _make_response([FULL_PLACE_RAW, FULL_PLACE_RAW])
    client = _make_client()
    results = client.search(_city_query())

    assert len(results) == 2
    assert mock_post.call_count == 1


@patch("time.sleep")
@patch("httpx.post")
def test_search_paginates_up_to_max_pages(mock_post, mock_sleep):
    page = [FULL_PLACE_RAW] * 20
    mock_post.side_effect = [
        _make_response(page, next_token="tok1"),
        _make_response(page, next_token="tok2"),
        _make_response([FULL_PLACE_RAW] * 10),  # last page, no token
    ]
    client = _make_client(max_pages=3)
    results = client.search(_city_query())

    assert len(results) == 50
    assert mock_post.call_count == 3


@patch("time.sleep")
@patch("httpx.post")
def test_search_stops_at_max_pages(mock_post, mock_sleep):
    page = [FULL_PLACE_RAW] * 20
    mock_post.return_value = _make_response(page, next_token="always-has-token")
    client = _make_client(max_pages=2)
    results = client.search(_city_query())

    assert len(results) == 40
    assert mock_post.call_count == 2


@patch("time.sleep")
@patch("httpx.post")
def test_search_passes_page_token_on_second_request(mock_post, mock_sleep):
    mock_post.side_effect = [
        _make_response([FULL_PLACE_RAW], next_token="mytoken"),
        _make_response([FULL_PLACE_RAW]),
    ]
    client = _make_client(max_pages=3)
    client.search(_city_query())

    second_call_body = mock_post.call_args_list[1].kwargs["json"]
    assert second_call_body.get("pageToken") == "mytoken"


# ---------------------------------------------------------------------------
# search — error handling
# ---------------------------------------------------------------------------


@patch("time.sleep")
@patch("httpx.post")
def test_search_raises_places_api_error_on_429(mock_post, mock_sleep):
    resp = MagicMock()
    resp.status_code = 429
    resp.text = "Quota exceeded"
    mock_post.return_value = resp

    with pytest.raises(PlacesAPIError) as exc_info:
        _make_client().search(_city_query())

    assert exc_info.value.status_code == 429


@patch("time.sleep")
@patch("httpx.post")
def test_search_raises_places_api_error_on_500(mock_post, mock_sleep):
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "Internal Server Error"
    mock_post.return_value = resp

    with pytest.raises(PlacesAPIError) as exc_info:
        _make_client().search(_city_query())

    assert exc_info.value.status_code == 500


@patch("time.sleep")
@patch("httpx.post")
def test_search_raises_places_api_error_on_network_error(mock_post, mock_sleep):
    import httpx

    mock_post.side_effect = httpx.ConnectError("connection refused")

    with pytest.raises(PlacesAPIError) as exc_info:
        _make_client().search(_city_query())

    assert exc_info.value.status_code is None


@patch("time.sleep")
@patch("httpx.post")
def test_search_returns_empty_list_when_no_places(mock_post, mock_sleep):
    mock_post.return_value = _make_response([])
    results = _make_client().search(_city_query())
    assert results == []


@patch("time.sleep")
@patch("httpx.post")
def test_search_returns_empty_list_when_places_key_absent(mock_post, mock_sleep):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {}  # no "places" key
    mock_post.return_value = resp

    results = _make_client().search(_city_query())
    assert results == []


# ---------------------------------------------------------------------------
# Rate limiting and headers
# ---------------------------------------------------------------------------


@patch("time.sleep")
@patch("httpx.post")
def test_rate_limit_delay_called_once_per_page(mock_post, mock_sleep):
    mock_post.return_value = _make_response([FULL_PLACE_RAW])
    client = _make_client(rate_limit_delay=0.5)
    client.search(_city_query())

    mock_sleep.assert_called_once_with(0.5)


@patch("time.sleep")
@patch("httpx.post")
def test_field_mask_header_sent(mock_post, mock_sleep):
    mock_post.return_value = _make_response([])
    _make_client().search(_city_query())

    headers = mock_post.call_args.kwargs["headers"]
    assert "X-Goog-FieldMask" in headers
    assert "places.id" in headers["X-Goog-FieldMask"]
    assert "X-Goog-Api-Key" in headers
    assert headers["X-Goog-Api-Key"] == "test-api-key"


# ---------------------------------------------------------------------------
# Request body per geo mode
# ---------------------------------------------------------------------------


@patch("time.sleep")
@patch("httpx.post")
def test_bounding_box_request_body(mock_post, mock_sleep):
    mock_post.return_value = _make_response([])
    query = GeoQuery(
        text_query="dentists",
        location_restriction={
            "rectangle": {
                "low": {"latitude": 51.4, "longitude": -0.3},
                "high": {"latitude": 51.6, "longitude": 0.1},
            }
        },
        method="bounding_box",
        center_lat=51.5,
        center_lng=-0.1,
        radius_m=None,
    )
    _make_client().search(query)

    body = mock_post.call_args.kwargs["json"]
    assert "locationRestriction" in body
    assert "rectangle" in body["locationRestriction"]
    assert body["locationRestriction"]["rectangle"]["low"]["latitude"] == 51.4
    assert "circle" not in body["locationRestriction"]


@patch("time.sleep")
@patch("httpx.post")
def test_center_radius_request_body(mock_post, mock_sleep):
    mock_post.return_value = _make_response([])
    query = GeoQuery(
        text_query="dentists",
        location_restriction={
            "circle": {
                "center": {"latitude": 51.5, "longitude": -0.12},
                "radius": 5000.0,
            }
        },
        method="center_radius",
        center_lat=51.5,
        center_lng=-0.12,
        radius_m=5000,
    )
    _make_client().search(query)

    body = mock_post.call_args.kwargs["json"]
    assert "locationRestriction" in body
    assert "circle" in body["locationRestriction"]
    assert body["locationRestriction"]["circle"]["radius"] == 5000.0
    assert "rectangle" not in body["locationRestriction"]


@patch("time.sleep")
@patch("httpx.post")
def test_city_request_body_no_location_restriction(mock_post, mock_sleep):
    mock_post.return_value = _make_response([])
    _make_client().search(_city_query())

    body = mock_post.call_args.kwargs["json"]
    assert "locationRestriction" not in body
    assert body["textQuery"] == "dentists in London, UK"


# ---------------------------------------------------------------------------
# includedType in request body
# ---------------------------------------------------------------------------


@patch("time.sleep")
@patch("httpx.post")
def test_included_type_added_to_request_body_when_set(mock_post, mock_sleep):
    """When GeoQuery.included_type is set, body must contain 'includedType'."""
    mock_post.return_value = _make_response([])
    query = GeoQuery(
        text_query="dentists in London, UK",
        location_restriction=None,
        method="city",
        center_lat=None,
        center_lng=None,
        radius_m=None,
        included_type="dentist",
    )
    _make_client().search(query)

    body = mock_post.call_args.kwargs["json"]
    assert body.get("includedType") == "dentist"


@patch("time.sleep")
@patch("httpx.post")
def test_included_type_absent_from_body_when_none(mock_post, mock_sleep):
    """When GeoQuery.included_type is None, 'includedType' must not appear in body."""
    mock_post.return_value = _make_response([])
    # _city_query() leaves included_type at default None
    _make_client().search(_city_query())

    body = mock_post.call_args.kwargs["json"]
    assert "includedType" not in body


# ---------------------------------------------------------------------------
# Dead-code removal regression — search() result count and identity
# ---------------------------------------------------------------------------


@patch("time.sleep")
@patch("httpx.post")
def test_search_returns_all_results_after_dead_code_removal(mock_post, mock_sleep):
    """search() must return every PlaceResult from every page unchanged."""
    page1 = [FULL_PLACE_RAW, {**FULL_PLACE_RAW, "id": "ChIJxxx"}]
    page2 = [{**FULL_PLACE_RAW, "id": "ChIJyyy"}]
    mock_post.side_effect = [
        _make_response(page1, next_token="tok"),
        _make_response(page2),
    ]
    results = _make_client(max_pages=3).search(_city_query())

    assert len(results) == 3
    assert results[0].place_id == "ChIJabc123"
    assert results[1].place_id == "ChIJxxx"
    assert results[2].place_id == "ChIJyyy"
