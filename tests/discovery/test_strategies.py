"""Unit tests for src/discovery/strategies.py.

Pure function tests — no mocking or DB connection required.
Campaign objects are replaced by lightweight SimpleNamespace stand-ins.
"""
from __future__ import annotations

import types

import pytest

from src.discovery.strategies import GeoQuery, build_queries
from src.models.enums import GeoMethod


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_campaign(**kwargs) -> types.SimpleNamespace:
    """Lightweight stand-in for a Campaign ORM object."""
    defaults = {
        "id": "test-campaign-id",
        "specialty": "dentists",
        "geo_method": GeoMethod.CITY,
        "geo_city": None,
        "geo_country": None,
        "geo_postal_code": None,
        "geo_sw_lat": None,
        "geo_sw_lng": None,
        "geo_ne_lat": None,
        "geo_ne_lng": None,
        "geo_center_lat": None,
        "geo_center_lng": None,
        "geo_radius_m": None,
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# City mode
# ---------------------------------------------------------------------------


def test_build_queries_city_mode_returns_list():
    c = make_campaign(geo_method=GeoMethod.CITY, geo_city="London", geo_country="UK")
    result = build_queries(c)
    assert isinstance(result, list)
    assert len(result) == 1


def test_build_queries_city_mode_text_query():
    c = make_campaign(geo_method=GeoMethod.CITY, geo_city="London", geo_country="UK")
    q = build_queries(c)[0]
    assert q.text_query == "dentists in London, UK"


def test_build_queries_city_mode_no_location_restriction():
    c = make_campaign(geo_method=GeoMethod.CITY, geo_city="London", geo_country="UK")
    q = build_queries(c)[0]
    assert q.location_restriction is None


def test_build_queries_city_mode_no_coords():
    c = make_campaign(geo_method=GeoMethod.CITY, geo_city="London", geo_country="UK")
    q = build_queries(c)[0]
    assert q.center_lat is None
    assert q.center_lng is None
    assert q.radius_m is None


def test_build_queries_city_mode_method_label():
    c = make_campaign(geo_method=GeoMethod.CITY, geo_city="London", geo_country="UK")
    q = build_queries(c)[0]
    assert q.method == "city"


def test_build_queries_city_mode_uses_specialty():
    c = make_campaign(
        geo_method=GeoMethod.CITY, geo_city="London", geo_country="UK",
        specialty="orthodontists",
    )
    q = build_queries(c)[0]
    assert q.text_query.startswith("orthodontists")


def test_build_queries_city_missing_city_raises():
    c = make_campaign(geo_method=GeoMethod.CITY, geo_city=None, geo_country="UK")
    with pytest.raises(ValueError):
        build_queries(c)


def test_build_queries_city_missing_country_raises():
    c = make_campaign(geo_method=GeoMethod.CITY, geo_city="London", geo_country=None)
    with pytest.raises(ValueError):
        build_queries(c)


# ---------------------------------------------------------------------------
# Postal code mode
# ---------------------------------------------------------------------------


def test_build_queries_postal_code_text_query():
    c = make_campaign(geo_method=GeoMethod.POSTAL_CODE, geo_postal_code="SW1A 1AA")
    q = build_queries(c)[0]
    assert q.text_query == "dentists in SW1A 1AA"


def test_build_queries_postal_code_no_location_restriction():
    c = make_campaign(geo_method=GeoMethod.POSTAL_CODE, geo_postal_code="SW1A 1AA")
    q = build_queries(c)[0]
    assert q.location_restriction is None


def test_build_queries_postal_code_method_label():
    c = make_campaign(geo_method=GeoMethod.POSTAL_CODE, geo_postal_code="SW1A 1AA")
    q = build_queries(c)[0]
    assert q.method == "postal_code"


def test_build_queries_postal_code_missing_raises():
    c = make_campaign(geo_method=GeoMethod.POSTAL_CODE, geo_postal_code=None)
    with pytest.raises(ValueError):
        build_queries(c)


# ---------------------------------------------------------------------------
# Bounding box mode
# ---------------------------------------------------------------------------


def test_build_queries_bounding_box_rectangle_structure():
    c = make_campaign(
        geo_method=GeoMethod.BOUNDING_BOX,
        geo_sw_lat=51.4, geo_sw_lng=-0.3,
        geo_ne_lat=51.6, geo_ne_lng=0.1,
    )
    q = build_queries(c)[0]
    rect = q.location_restriction["rectangle"]
    assert rect["low"] == {"latitude": 51.4, "longitude": -0.3}
    assert rect["high"] == {"latitude": 51.6, "longitude": 0.1}


def test_build_queries_bounding_box_center_average():
    c = make_campaign(
        geo_method=GeoMethod.BOUNDING_BOX,
        geo_sw_lat=51.4, geo_sw_lng=-0.3,
        geo_ne_lat=51.6, geo_ne_lng=0.1,
    )
    q = build_queries(c)[0]
    assert q.center_lat == pytest.approx(51.5)
    assert q.center_lng == pytest.approx(-0.1)


def test_build_queries_bounding_box_no_radius():
    c = make_campaign(
        geo_method=GeoMethod.BOUNDING_BOX,
        geo_sw_lat=51.4, geo_sw_lng=-0.3,
        geo_ne_lat=51.6, geo_ne_lng=0.1,
    )
    q = build_queries(c)[0]
    assert q.radius_m is None


def test_build_queries_bounding_box_text_query_is_specialty():
    c = make_campaign(
        geo_method=GeoMethod.BOUNDING_BOX,
        geo_sw_lat=51.4, geo_sw_lng=-0.3,
        geo_ne_lat=51.6, geo_ne_lng=0.1,
        specialty="dentists",
    )
    q = build_queries(c)[0]
    assert q.text_query == "dentists"


def test_build_queries_bounding_box_method_label():
    c = make_campaign(
        geo_method=GeoMethod.BOUNDING_BOX,
        geo_sw_lat=51.4, geo_sw_lng=-0.3,
        geo_ne_lat=51.6, geo_ne_lng=0.1,
    )
    q = build_queries(c)[0]
    assert q.method == "bounding_box"


def test_build_queries_bounding_box_missing_sw_lat_raises():
    c = make_campaign(
        geo_method=GeoMethod.BOUNDING_BOX,
        geo_sw_lat=None, geo_sw_lng=-0.3,
        geo_ne_lat=51.6, geo_ne_lng=0.1,
    )
    with pytest.raises(ValueError):
        build_queries(c)


def test_build_queries_bounding_box_missing_ne_lng_raises():
    c = make_campaign(
        geo_method=GeoMethod.BOUNDING_BOX,
        geo_sw_lat=51.4, geo_sw_lng=-0.3,
        geo_ne_lat=51.6, geo_ne_lng=None,
    )
    with pytest.raises(ValueError):
        build_queries(c)


# ---------------------------------------------------------------------------
# Center + radius mode
# ---------------------------------------------------------------------------


def test_build_queries_center_radius_circle_structure():
    c = make_campaign(
        geo_method=GeoMethod.CENTER_RADIUS,
        geo_center_lat=51.5074, geo_center_lng=-0.1278,
        geo_radius_m=5000,
    )
    q = build_queries(c)[0]
    circle = q.location_restriction["circle"]
    assert circle["center"] == {"latitude": 51.5074, "longitude": -0.1278}
    assert circle["radius"] == 5000.0


def test_build_queries_center_radius_lat_lng_stored():
    c = make_campaign(
        geo_method=GeoMethod.CENTER_RADIUS,
        geo_center_lat=51.5074, geo_center_lng=-0.1278,
        geo_radius_m=5000,
    )
    q = build_queries(c)[0]
    assert q.center_lat == 51.5074
    assert q.center_lng == -0.1278
    assert q.radius_m == 5000


def test_build_queries_center_radius_method_label():
    c = make_campaign(
        geo_method=GeoMethod.CENTER_RADIUS,
        geo_center_lat=51.5074, geo_center_lng=-0.1278,
        geo_radius_m=5000,
    )
    q = build_queries(c)[0]
    assert q.method == "center_radius"


def test_build_queries_center_radius_text_query_is_specialty():
    c = make_campaign(
        geo_method=GeoMethod.CENTER_RADIUS,
        geo_center_lat=51.5074, geo_center_lng=-0.1278,
        geo_radius_m=5000,
        specialty="dentists",
    )
    q = build_queries(c)[0]
    assert q.text_query == "dentists"


def test_build_queries_center_radius_missing_radius_raises():
    c = make_campaign(
        geo_method=GeoMethod.CENTER_RADIUS,
        geo_center_lat=51.5074, geo_center_lng=-0.1278,
        geo_radius_m=None,
    )
    with pytest.raises(ValueError):
        build_queries(c)


def test_build_queries_center_radius_missing_center_lat_raises():
    c = make_campaign(
        geo_method=GeoMethod.CENTER_RADIUS,
        geo_center_lat=None, geo_center_lng=-0.1278,
        geo_radius_m=5000,
    )
    with pytest.raises(ValueError):
        build_queries(c)
