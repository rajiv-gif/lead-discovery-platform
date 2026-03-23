"""Lead Discovery Platform — internal dashboard.

FastAPI application serving a Jinja2 + HTMX UI over the existing pipeline.

IMPORTANT: Single-process, single-worker only.
The task registry (``src.dashboard.tasks``) is in-memory and is NOT safe for
multi-worker or multi-process deployments. Always run with one worker:

    uvicorn src.dashboard.app:app --reload
    # or
    leads-ui

Task state does not survive server restarts. Pipeline DB state is always
the ground truth; page counts are read live from the database.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from src.config.settings import settings
from src.dashboard.auth import BasicAuthMiddleware
from src.dashboard.routes import api, campaigns, detail, export, pipeline, review, status

app = FastAPI(
    title="Lead Discovery Dashboard",
    description="Internal dashboard for the lead discovery pipeline.",
    docs_url=None,   # disable Swagger UI for internal tool
    redoc_url=None,
)

# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------
# Enabled when DASHBOARD_USERNAME and DASHBOARD_PASSWORD are both set.
# /healthz is always exempt for Railway health checks.

if settings.dashboard_username and settings.dashboard_password:
    app.add_middleware(
        BasicAuthMiddleware,
        username=settings.dashboard_username,
        password=settings.dashboard_password,
    )

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(api.router)
app.include_router(campaigns.router)
app.include_router(detail.router)
app.include_router(pipeline.router)
app.include_router(status.router)
app.include_router(review.router)
app.include_router(export.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/healthz", response_class=JSONResponse, include_in_schema=False)
async def healthz() -> JSONResponse:
    """Lightweight liveness probe — returns 200 if the process is alive.

    Does not check DB connectivity; use ``leads db check`` for that.
    """
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Entry point for ``leads-ui`` CLI script
# ---------------------------------------------------------------------------

def start() -> None:
    """Start the dashboard with Uvicorn (single worker, single process)."""
    import uvicorn

    uvicorn.run(
        "src.dashboard.app:app",
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        reload=False,
        workers=1,  # MUST be 1 — task registry is not multi-worker safe
    )
