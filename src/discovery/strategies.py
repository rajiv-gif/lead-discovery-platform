"""Geo-query strategy builders for Google Places discovery.

Each strategy translates a Campaign's geo configuration into one or more
``GeoQuery`` objects that can be passed directly to ``PlacesClient.search()``.

All strategies currently return a single-element list. The list wrapper is
intentional — future phases may split large geographies into sub-queries
(e.g. grid tiles for large bounding boxes) without changing callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.models.enums import GeoMethod

if TYPE_CHECKING:
    from src.models.campaign import Campaign


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GeoQuery:
    """A single Places API query derived from a Campaign's geo configuration.

    Attributes:
        text_query: The ``textQuery`` field sent to the Places API.
        location_restriction: Optional ``locationRestriction`` body fragment
            (rectangle or circle). None for city/postal_code modes, which rely
            on the text query alone for geographic bias.
        method: Lowercase ``GeoMethod`` value; stored verbatim on
            ``DiscoveryHit.discovery_method`` for audit/debugging.
        center_lat: Geographic centre latitude of the query region, or None
            for modes that do not specify a coordinate (city, postal_code).
        center_lng: Geographic centre longitude of the query region, or None.
        radius_m: Query radius in metres, or None for non-circle queries.
    """

    text_query: str
    location_restriction: Optional[dict]
    method: str
    center_lat: Optional[float]
    center_lng: Optional[float]
    radius_m: Optional[int]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_queries(campaign: Campaign) -> list[GeoQuery]:
    """Return the list of ``GeoQuery`` objects for *campaign*.

    Dispatches on ``campaign.geo_method`` and calls the appropriate
    private builder.

    Raises:
        ValueError: If a required geo field for the chosen method is missing.
    """
    method = campaign.geo_method

    if method == GeoMethod.CITY:
        return _city_queries(campaign)
    if method == GeoMethod.POSTAL_CODE:
        return _postal_code_queries(campaign)
    if method == GeoMethod.BOUNDING_BOX:
        return _bounding_box_queries(campaign)
    if method == GeoMethod.CENTER_RADIUS:
        return _center_radius_queries(campaign)

    raise ValueError(f"Unsupported geo method: {method!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Private builders
# ---------------------------------------------------------------------------


def _city_queries(campaign: Campaign) -> list[GeoQuery]:
    if not campaign.geo_city or not campaign.geo_country:
        raise ValueError(
            f"Campaign {campaign.id}: geo_city and geo_country are required for CITY mode"
        )
    text_query = f"{campaign.specialty} in {campaign.geo_city}, {campaign.geo_country}"
    return [
        GeoQuery(
            text_query=text_query,
            location_restriction=None,
            method=GeoMethod.CITY.value,
            center_lat=None,
            center_lng=None,
            radius_m=None,
        )
    ]


def _postal_code_queries(campaign: Campaign) -> list[GeoQuery]:
    if not campaign.geo_postal_code:
        raise ValueError(
            f"Campaign {campaign.id}: geo_postal_code is required for POSTAL_CODE mode"
        )
    text_query = f"{campaign.specialty} in {campaign.geo_postal_code}"
    return [
        GeoQuery(
            text_query=text_query,
            location_restriction=None,
            method=GeoMethod.POSTAL_CODE.value,
            center_lat=None,
            center_lng=None,
            radius_m=None,
        )
    ]


def _bounding_box_queries(campaign: Campaign) -> list[GeoQuery]:
    if any(
        v is None
        for v in (campaign.geo_sw_lat, campaign.geo_sw_lng,
                  campaign.geo_ne_lat, campaign.geo_ne_lng)
    ):
        raise ValueError(
            f"Campaign {campaign.id}: "
            "geo_sw_lat, geo_sw_lng, geo_ne_lat, geo_ne_lng are required for BOUNDING_BOX mode"
        )
    location_restriction = {
        "rectangle": {
            "low": {
                "latitude": campaign.geo_sw_lat,
                "longitude": campaign.geo_sw_lng,
            },
            "high": {
                "latitude": campaign.geo_ne_lat,
                "longitude": campaign.geo_ne_lng,
            },
        }
    }
    # Geometric centre of the bounding box — stored on discovery_hits for audit.
    center_lat = (campaign.geo_sw_lat + campaign.geo_ne_lat) / 2
    center_lng = (campaign.geo_sw_lng + campaign.geo_ne_lng) / 2
    return [
        GeoQuery(
            text_query=campaign.specialty,
            location_restriction=location_restriction,
            method=GeoMethod.BOUNDING_BOX.value,
            center_lat=center_lat,
            center_lng=center_lng,
            radius_m=None,
        )
    ]


def _center_radius_queries(campaign: Campaign) -> list[GeoQuery]:
    if any(
        v is None
        for v in (campaign.geo_center_lat, campaign.geo_center_lng, campaign.geo_radius_m)
    ):
        raise ValueError(
            f"Campaign {campaign.id}: "
            "geo_center_lat, geo_center_lng, geo_radius_m are required for CENTER_RADIUS mode"
        )
    location_restriction = {
        "circle": {
            "center": {
                "latitude": campaign.geo_center_lat,
                "longitude": campaign.geo_center_lng,
            },
            "radius": float(campaign.geo_radius_m),
        }
    }
    return [
        GeoQuery(
            text_query=campaign.specialty,
            location_restriction=location_restriction,
            method=GeoMethod.CENTER_RADIUS.value,
            center_lat=campaign.geo_center_lat,
            center_lng=campaign.geo_center_lng,
            radius_m=campaign.geo_radius_m,
        )
    ]
