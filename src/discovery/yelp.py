"""Yelp Fusion API client for supplemental lead discovery.

Uses the Yelp Fusion Business Search and Business Details endpoints to find
local businesses not captured by Google Places, returning the same
``PlaceResult`` data structure so the rest of the pipeline is source-agnostic.

Requires a free Yelp Fusion API key (YELP_API_KEY in .env).
Free tier: 500 calls/day for search, 500 calls/day for details.

Reference:
  https://docs.developer.yelp.com/reference/v3_businesses_search
  https://docs.developer.yelp.com/reference/v3_businesses_info
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

import httpx

from src.discovery.places import PlaceResult

if TYPE_CHECKING:
    from src.models.campaign import Campaign

log = logging.getLogger(__name__)

_SEARCH_URL = "https://api.yelp.com/v3/businesses/search"
_DETAILS_URL = "https://api.yelp.com/v3/businesses/{id}"

# Yelp max radius is 40,000 metres.
_MAX_RADIUS_M = 40_000


class YelpClient:
    """Thin synchronous wrapper around the Yelp Fusion API.

    Args:
        api_key: Yelp Fusion API key (Bearer token).
        rate_limit_delay: Seconds to sleep between API requests.
        max_results: Maximum total results to return per search (50/page, max 240).
    """

    def __init__(
        self,
        api_key: str,
        rate_limit_delay: float = 0.5,
        max_results: int = 100,
    ) -> None:
        self._api_key = api_key
        self._rate_limit_delay = rate_limit_delay
        self._max_results = min(max_results, 240)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search_for_campaign(self, campaign: Campaign) -> list[PlaceResult]:
        """Search Yelp for businesses matching *campaign*'s specialty + geo.

        Returns a flat list of ``PlaceResult`` objects, one per unique business.
        """
        from src.models.enums import GeoMethod

        method = campaign.geo_method
        specialty = campaign.specialty

        if method == GeoMethod.CITY:
            if not campaign.geo_city or not campaign.geo_country:
                raise ValueError("geo_city and geo_country required for CITY mode")
            location = f"{campaign.geo_city}, {campaign.geo_country}"
            return self._search(specialty, location=location)

        if method == GeoMethod.POSTAL_CODE:
            if not campaign.geo_postal_code:
                raise ValueError("geo_postal_code required for POSTAL_CODE mode")
            return self._search(specialty, location=campaign.geo_postal_code)

        if method == GeoMethod.CENTER_RADIUS:
            if any(v is None for v in (campaign.geo_center_lat, campaign.geo_center_lng, campaign.geo_radius_m)):
                raise ValueError("center_lat, center_lng, radius_m required for CENTER_RADIUS mode")
            radius = min(campaign.geo_radius_m, _MAX_RADIUS_M)
            return self._search(
                specialty,
                latitude=campaign.geo_center_lat,
                longitude=campaign.geo_center_lng,
                radius_m=radius,
            )

        if method == GeoMethod.BOUNDING_BOX:
            if any(v is None for v in (campaign.geo_sw_lat, campaign.geo_sw_lng, campaign.geo_ne_lat, campaign.geo_ne_lng)):
                raise ValueError("All bounding box coordinates required")
            # Approximate: use centre + half-diagonal as radius
            center_lat = (campaign.geo_sw_lat + campaign.geo_ne_lat) / 2
            center_lng = (campaign.geo_sw_lng + campaign.geo_ne_lng) / 2
            # Rough km-to-metres using latitude degree ≈ 111km
            lat_span_m = abs(campaign.geo_ne_lat - campaign.geo_sw_lat) * 111_000
            lng_span_m = abs(campaign.geo_ne_lng - campaign.geo_sw_lng) * 85_000
            radius = int(min((lat_span_m**2 + lng_span_m**2) ** 0.5 / 2, _MAX_RADIUS_M))
            return self._search(
                specialty,
                latitude=center_lat,
                longitude=center_lng,
                radius_m=radius,
            )

        raise ValueError(f"Unsupported geo method: {method!r}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search(
        self,
        term: str,
        location: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_m: Optional[int] = None,
    ) -> list[PlaceResult]:
        """Paginate Yelp search and return all results up to ``max_results``."""
        results: list[PlaceResult] = []
        offset = 0
        page_size = 50  # Yelp max per request

        while len(results) < self._max_results:
            params: dict = {
                "term": term,
                "limit": min(page_size, self._max_results - len(results)),
                "offset": offset,
            }
            if location is not None:
                params["location"] = location
            if latitude is not None:
                params["latitude"] = latitude
                params["longitude"] = longitude
            if radius_m is not None:
                params["radius"] = radius_m

            try:
                resp = httpx.get(
                    _SEARCH_URL, params=params, headers=self._headers, timeout=30.0
                )
            except httpx.HTTPError as exc:
                log.error("Yelp search network error: %s", exc)
                break
            finally:
                time.sleep(self._rate_limit_delay)

            if resp.status_code == 429:
                log.warning("Yelp rate limit hit (429) — stopping pagination")
                break
            if resp.status_code >= 400:
                log.error("Yelp search error HTTP %d: %s", resp.status_code, resp.text[:200])
                break

            data = resp.json()
            businesses: list[dict] = data.get("businesses") or []
            total: int = data.get("total", 0)

            if not businesses:
                break

            for biz in businesses:
                place = self._parse_business(biz)
                if place is not None:
                    results.append(place)

            offset += len(businesses)
            if offset >= total or offset >= 240:  # Yelp hard caps at 240
                break

        # Fetch website URLs for each result (separate detail call)
        enriched: list[PlaceResult] = []
        for place in results:
            website = self._fetch_website(place.place_id)
            if website:
                domain = self._extract_domain(website)
                enriched.append(PlaceResult(
                    place_id=place.place_id,
                    name=place.name,
                    formatted_address=place.formatted_address,
                    website_uri=website,
                    domain=domain,
                    phone_number=place.phone_number,
                    rating=place.rating,
                    user_rating_count=place.user_rating_count,
                    latitude=place.latitude,
                    longitude=place.longitude,
                    city=place.city,
                    state=place.state,
                    country=place.country,
                    country_code=place.country_code,
                    postal_code=place.postal_code,
                    business_status=place.business_status,
                    types=place.types,
                    raw=place.raw,
                ))
            else:
                enriched.append(place)

        log.info("Yelp search returned %d results for %r", len(enriched), term)
        return enriched

    def _fetch_website(self, yelp_id: str) -> Optional[str]:
        """Fetch business details to get the business's own website URL.

        Returns the value of the ``website`` field from the Yelp business
        details response, or ``None`` when the business has no website on
        file or the request fails.

        IMPORTANT: The ``url`` field in the Yelp response is the Yelp listing
        page URL (e.g. https://www.yelp.com/biz/...).  We deliberately ignore
        it.  Storing a Yelp listing URL as company.website would set
        company.domain = "www.yelp.com", breaking domain-based dedup for all
        Yelp-sourced companies.
        """
        url = _DETAILS_URL.format(id=yelp_id)
        try:
            resp = httpx.get(url, headers=self._headers, timeout=15.0)
        except httpx.HTTPError as exc:
            log.debug("Yelp details fetch error for %s: %s", yelp_id, exc)
            return None
        finally:
            time.sleep(self._rate_limit_delay)

        if resp.status_code != 200:
            return None

        data = resp.json()
        # ``website`` is the business's own URL — may be absent or empty.
        # ``url`` is the Yelp listing page — never use it as the business website.
        website = data.get("website") or None
        return website

    def _parse_business(self, biz: dict) -> Optional[PlaceResult]:
        """Map a raw Yelp business dict to a ``PlaceResult``."""
        yelp_id: str = biz.get("id", "")
        name: str = biz.get("name", "")
        if not yelp_id or not name:
            return None

        location: dict = biz.get("location") or {}
        coords: dict = biz.get("coordinates") or {}

        address_parts = [p for p in [
            location.get("address1"),
            location.get("address2"),
        ] if p]
        city = location.get("city")
        state = location.get("state")
        country_code = location.get("country")
        postal_code = location.get("zip_code")

        address_line = ", ".join(address_parts)
        full_address = ", ".join(filter(None, [
            address_line, city,
            f"{state} {postal_code}".strip() if state or postal_code else None,
            country_code,
        ]))

        categories = [c.get("title", "") for c in (biz.get("categories") or [])]

        return PlaceResult(
            place_id=f"yelp:{yelp_id}",
            name=name,
            formatted_address=full_address or None,
            website_uri=None,   # filled in by _fetch_website
            domain=None,
            phone_number=biz.get("phone") or None,
            rating=biz.get("rating"),
            user_rating_count=biz.get("review_count"),
            latitude=coords.get("latitude"),
            longitude=coords.get("longitude"),
            city=city,
            state=state,
            country=None,
            country_code=country_code,
            postal_code=postal_code,
            business_status="OPERATIONAL" if not biz.get("is_closed") else "CLOSED",
            types=categories,
            raw=biz,
        )

    @staticmethod
    def _extract_domain(uri: Optional[str]) -> Optional[str]:
        if not uri:
            return None
        try:
            return urlparse(uri).netloc or None
        except Exception:
            return None
