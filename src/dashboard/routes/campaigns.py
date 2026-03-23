"""Campaign list and create routes."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from src.dashboard.deps import templates
from src.db.session import get_session
from src.discovery.city_lists import get_countries, get_states
from src.models.campaign import Campaign
from src.models.enums import CampaignStatus, DiscoverySource, GeoMethod

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def campaign_list(request: Request) -> HTMLResponse:
    with get_session() as session:
        campaigns = session.execute(
            select(Campaign).order_by(Campaign.created_at.desc())
        ).scalars().all()

    return templates.TemplateResponse(
        request,
        "campaigns/list.html",
        {"campaigns": campaigns},
    )


@router.get("/campaigns/new", response_class=HTMLResponse)
async def campaign_create_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "campaigns/create.html",
        {
            "geo_methods": [m.value for m in GeoMethod],
            "countries": get_countries(),
            "us_states": get_states("United States"),
            "error": None,
        },
    )


@router.post("/campaigns/new")
async def campaign_create(request: Request):
    form = await request.form()

    name = (form.get("name") or "").strip()
    niche = (form.get("niche") or "dentists").strip()
    description = (form.get("description") or "").strip() or None
    discovery_source_raw = (form.get("discovery_source") or "google_places").strip()

    def _err(msg: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "campaigns/create.html",
            {
                "geo_methods": [m.value for m in GeoMethod],
                "countries": get_countries(),
                "us_states": get_states("United States"),
                "error": msg,
                "form": dict(form),
            },
            status_code=422,
        )

    if not name:
        return _err("Campaign name is required.")

    try:
        discovery_source = DiscoverySource(discovery_source_raw)
    except ValueError:
        return _err(f"Invalid discovery source: {discovery_source_raw!r}")

    # --- WEB_SEARCH campaign ---
    if discovery_source == DiscoverySource.WEB_SEARCH:
        raw_queries = (form.get("search_queries") or "").strip()
        search_queries = [q.strip() for q in raw_queries.splitlines() if q.strip()]
        if not search_queries:
            return _err("At least one search query is required for web search campaigns.")

        with get_session() as session:
            campaign = Campaign(
                name=name,
                description=description,
                niche=niche,
                status=CampaignStatus.DRAFT,
                discovery_source=DiscoverySource.WEB_SEARCH,
                search_queries=search_queries,
            )
            session.add(campaign)
            session.flush()
            campaign_id = str(campaign.id)

        return RedirectResponse(f"/campaigns/{campaign_id}", status_code=303)

    # --- GOOGLE_PLACES campaign ---
    geo_method_raw = (form.get("geo_method") or "").strip()

    try:
        geo_method = GeoMethod(geo_method_raw)
    except ValueError:
        return _err(f"Invalid geo method: {geo_method_raw!r}")

    def _float(key: str):
        val = form.get(key, "").strip()
        return float(val) if val else None

    def _int(key: str):
        val = form.get(key, "").strip()
        return int(val) if val else None

    city = (form.get("city") or "").strip() or None
    country = (form.get("country") or "").strip() or None
    postal_code = (form.get("postal_code") or "").strip() or None
    geo_state = (form.get("geo_state") or "").strip() or None
    sw_lat = _float("sw_lat")
    sw_lng = _float("sw_lng")
    ne_lat = _float("ne_lat")
    ne_lng = _float("ne_lng")
    center_lat = _float("center_lat")
    center_lng = _float("center_lng")
    radius_m = _int("radius_m")

    # geo_cities_selected comes as a multi-value form field
    geo_cities_selected = form.getlist("geo_cities_selected") or []

    # Validate required geo fields
    if geo_method == GeoMethod.CITY and not (city and country):
        return _err("City and country are required for city mode.")
    if geo_method == GeoMethod.POSTAL_CODE and not postal_code:
        return _err("Postal code is required.")
    if geo_method == GeoMethod.BOUNDING_BOX and any(
        v is None for v in (sw_lat, sw_lng, ne_lat, ne_lng)
    ):
        return _err("All four bounding box coordinates are required.")
    if geo_method == GeoMethod.CENTER_RADIUS and any(
        v is None for v in (center_lat, center_lng, radius_m)
    ):
        return _err("Center lat, center lng, and radius are required.")
    if geo_method == GeoMethod.STATE:
        if not geo_state or not country:
            return _err("State and country are required for state mode.")
        if not geo_cities_selected:
            return _err("Select at least one city for state mode.")

    with get_session() as session:
        campaign = Campaign(
            name=name,
            description=description,
            niche=niche,
            status=CampaignStatus.DRAFT,
            discovery_source=DiscoverySource.GOOGLE_PLACES,
            geo_method=geo_method,
            geo_city=city,
            geo_country=country,
            geo_state=geo_state,
            geo_cities_selected=geo_cities_selected if geo_cities_selected else None,
            geo_postal_code=postal_code,
            geo_sw_lat=sw_lat,
            geo_sw_lng=sw_lng,
            geo_ne_lat=ne_lat,
            geo_ne_lng=ne_lng,
            geo_center_lat=center_lat,
            geo_center_lng=center_lng,
            geo_radius_m=radius_m,
        )
        session.add(campaign)
        session.flush()
        campaign_id = str(campaign.id)

    return RedirectResponse(f"/campaigns/{campaign_id}", status_code=303)
