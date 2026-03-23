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
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from src.config.settings import settings
from src.dashboard.auth import SessionAuthMiddleware
from src.dashboard.routes import api, campaigns, detail, export, pipeline, review, status
from src.dashboard.routes import auth as auth_routes

app = FastAPI(
    title="Lead Discovery Dashboard",
    description="Internal dashboard for the lead discovery pipeline.",
    docs_url=None,   # disable Swagger UI for internal tool
    redoc_url=None,
)

# ---------------------------------------------------------------------------
# Session middleware — must be outermost so session is available to auth
# Signs and verifies the session cookie with SESSION_SECRET_KEY.
# ---------------------------------------------------------------------------

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie="ld_session",
    max_age=60 * 60 * 24 * 7,   # 7-day session
    same_site="lax",
    https_only=False,             # Railway terminates TLS; cookies come over HTTP internally
)

# ---------------------------------------------------------------------------
# Auth middleware — redirects unauthenticated requests to /login
# ---------------------------------------------------------------------------

app.add_middleware(
    SessionAuthMiddleware,
    username=settings.dashboard_username,
    password=settings.dashboard_password,
)

# Store a verifier on app.state so the login route can call .verify()
# without walking the middleware stack.
app.state.auth_middleware = SessionAuthMiddleware(
    app=None,
    username=settings.dashboard_username,
    password=settings.dashboard_password,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_routes.router)
app.include_router(api.router)
app.include_router(campaigns.router)
app.include_router(detail.router)
app.include_router(pipeline.router)
app.include_router(status.router)
app.include_router(review.router)
app.include_router(export.router)


# ---------------------------------------------------------------------------
# Health check (always exempt — Railway uses this to check the service is up)
# ---------------------------------------------------------------------------

@app.get("/healthz", response_class=JSONResponse, include_in_schema=False)
async def healthz() -> JSONResponse:
    """Lightweight liveness probe — returns 200 if the process is alive."""
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
