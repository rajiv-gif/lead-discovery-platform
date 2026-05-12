"""Dashboard settings page."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.config import runtime
from src.config.settings import settings
from src.dashboard.deps import templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    extraction_provider = runtime.get("extraction_provider", settings.extraction_provider or "local")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "extraction_provider": extraction_provider,
            "ollama_configured": bool(settings.ollama_base_url),
            "anthropic_configured": bool(settings.anthropic_api_key),
            "ollama_model": settings.ollama_model,
            "extraction_model": settings.extraction_model,
        },
    )


@router.post("/settings/extraction-provider")
async def set_extraction_provider(request: Request):
    form = await request.form()
    provider = (form.get("extraction_provider") or "local").strip().lower()
    if provider not in ("local", "anthropic"):
        provider = "local"
    runtime.set("extraction_provider", provider)
    return RedirectResponse("/settings", status_code=303)
