"""Internal API endpoints for HTMX-driven UI components.

/api/cities  — returns a city checklist partial for the campaign creation form.
/api/states  — returns the list of states for a country (JSON).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.dashboard.deps import templates
from src.discovery.city_lists import get_cities, get_countries, get_states

router = APIRouter(prefix="/api")


@router.get("/states", response_class=JSONResponse)
async def list_states(country: str = "United States") -> JSONResponse:
    """Return sorted list of states for *country* as JSON array."""
    return JSONResponse(get_states(country))


@router.get("/countries", response_class=JSONResponse)
async def list_countries() -> JSONResponse:
    """Return supported country names as JSON array."""
    return JSONResponse(get_countries())


@router.get("/cities", response_class=HTMLResponse)
async def city_checklist(
    request: Request,
    state: str = "",
    country: str = "United States",
) -> HTMLResponse:
    """Return the city checklist partial for the given state.

    Called via HTMX when the user selects a state in the campaign creation form.
    Returns an HTML partial rendered from ``partials/city_checklist.html``.
    """
    cities = get_cities(state, country) if state else []
    return templates.TemplateResponse(
        request,
        "partials/city_checklist.html",
        {
            "cities": cities,
            "state": state,
            "country": country,
        },
    )
