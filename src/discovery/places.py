"""Google Places API v1 client for lead discovery.

Uses the Places API (New) Text Search endpoint:
  POST https://places.googleapis.com/v1/places:searchText

Reference:
  https://developers.google.com/maps/documentation/places/web-service/text-search
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from src.discovery.strategies import GeoQuery

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PlacesAPIError(Exception):
    """Raised for any non-retryable Places API failure.

    Attributes:
        status_code: HTTP status code, or None for network-level errors.
    """

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PlaceResult:
    """Normalised representation of a single Google Places API result.

    All fields except ``place_id`` and ``name`` are optional — the API does
    not guarantee all fields are present for every place.
    """

    place_id: str
    name: str
    formatted_address: Optional[str] = None
    website_uri: Optional[str] = None
    # Extracted from website_uri via urllib.parse — used for company dedup.
    domain: Optional[str] = None
    # International phone number (E.164-ish format).
    phone_number: Optional[str] = None
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Derived from addressComponents
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    postal_code: Optional[str] = None
    business_status: Optional[str] = None
    types: list[str] = field(default_factory=list)
    # Full raw API response dict for storage in Company.extra_fields.
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class PlacesClient:
    """Thin, synchronous wrapper around the Google Places API v1 Text Search.

    Args:
        api_key: Google Places API key (required).
        rate_limit_delay: Seconds to sleep after each API request.
        max_pages: Maximum number of result pages to fetch per query
                   (20 results per page, so max_pages=3 → up to 60 results).
    """

    BASE_URL = "https://places.googleapis.com/v1/places:searchText"

    # Fields requested from the API. Adjust only when adding new mappings to
    # PlaceResult; unnecessary fields increase response size and cost.
    FIELD_MASK = (
        "places.id,"
        "places.displayName,"
        "places.formattedAddress,"
        "places.websiteUri,"
        "places.internationalPhoneNumber,"
        "places.rating,"
        "places.userRatingCount,"
        "places.location,"
        "places.addressComponents,"
        "places.businessStatus,"
        "places.types,"
        "nextPageToken"
    )

    def __init__(
        self,
        api_key: str,
        rate_limit_delay: float = 0.5,
        max_pages: int = 3,
    ) -> None:
        self._api_key = api_key
        self._rate_limit_delay = rate_limit_delay
        self._max_pages = max_pages
        self._headers = {
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": self.FIELD_MASK,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, query: GeoQuery) -> list[PlaceResult]:
        """Execute *query*, paginating up to ``max_pages``.

        Returns:
            Flat list of all ``PlaceResult`` objects, ranked by API order.

        Raises:
            PlacesAPIError: On any non-retryable API failure.
        """
        results: list[PlaceResult] = []
        page_token: Optional[str] = None

        for page_num in range(self._max_pages):
            page_results, next_token = self._request_page(
                text_query=query.text_query,
                location_restriction=query.location_restriction,
                page_token=page_token,
                included_type=query.included_type,
            )

            results.extend(page_results)

            log.debug(
                "Places page %d/%d: %d results (query=%r)",
                page_num + 1,
                self._max_pages,
                len(page_results),
            )

            if next_token is None:
                break
            page_token = next_token

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request_page(
        self,
        text_query: str,
        location_restriction: Optional[dict],
        page_token: Optional[str],
        included_type: Optional[str] = None,
    ) -> tuple[list[PlaceResult], Optional[str]]:
        """Make a single POST request and return ``(results, next_page_token)``."""
        body: dict = {
            "textQuery": text_query,
            "languageCode": "en",
            "maxResultCount": 20,
        }
        if location_restriction is not None:
            body["locationRestriction"] = location_restriction
        if page_token is not None:
            body["pageToken"] = page_token
        if included_type is not None:
            body["includedType"] = included_type

        try:
            response = httpx.post(
                self.BASE_URL,
                json=body,
                headers=self._headers,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise PlacesAPIError(f"Network error contacting Places API: {exc}") from exc
        finally:
            # Always sleep after a request attempt to respect rate limits,
            # even when the request fails — a failed request still counts
            # against the per-second quota.
            time.sleep(self._rate_limit_delay)

        if response.status_code == 429:
            raise PlacesAPIError(
                f"Places API quota exceeded (HTTP 429) for query: {text_query!r}",
                status_code=429,
            )
        if response.status_code >= 400:
            raise PlacesAPIError(
                f"Places API error HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )

        data = response.json()
        raw_places: list[dict] = data.get("places") or []
        next_token: Optional[str] = data.get("nextPageToken")

        parsed = [self._parse_place(raw, rank=i) for i, raw in enumerate(raw_places)]
        return parsed, next_token

    def _parse_place(self, raw: dict, rank: int) -> PlaceResult:
        """Map a single raw API place dict to a ``PlaceResult``."""
        components: list[dict] = raw.get("addressComponents") or []
        location = raw.get("location") or {}
        website_uri: Optional[str] = raw.get("websiteUri")

        return PlaceResult(
            place_id=raw["id"],
            name=(raw.get("displayName") or {}).get("text", ""),
            formatted_address=raw.get("formattedAddress"),
            website_uri=website_uri,
            domain=self._extract_domain(website_uri),
            phone_number=raw.get("internationalPhoneNumber"),
            rating=raw.get("rating"),
            user_rating_count=raw.get("userRatingCount"),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            city=self._extract_address_component(components, "locality"),
            state=self._extract_address_component(components, "administrative_area_level_1"),
            country=self._extract_address_component(components, "country", "longText"),
            country_code=self._extract_address_component(components, "country", "shortText"),
            postal_code=self._extract_address_component(components, "postal_code"),
            business_status=raw.get("businessStatus"),
            types=raw.get("types") or [],
            raw=raw,
        )

    @staticmethod
    def _extract_domain(uri: Optional[str]) -> Optional[str]:
        """Return the netloc (host) from *uri*, or None if unparseable."""
        if not uri:
            return None
        try:
            parsed = urlparse(uri)
            return parsed.netloc or None
        except Exception:
            return None

    @staticmethod
    def _extract_address_component(
        components: list[dict],
        type_: str,
        name_type: str = "longText",
    ) -> Optional[str]:
        """Return the first component whose ``types`` list contains *type_*."""
        for component in components:
            if type_ in (component.get("types") or []):
                return component.get(name_type)
        return None
