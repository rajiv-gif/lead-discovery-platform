"""Login / logout routes."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.config.settings import settings
from src.dashboard.auth import SessionAuthMiddleware
from src.dashboard.deps import templates

router = APIRouter()


def _get_middleware(request: Request) -> SessionAuthMiddleware | None:
    """Find the SessionAuthMiddleware instance from the app middleware stack."""
    for middleware in request.app.middleware_stack.middlewares if hasattr(request.app.middleware_stack, "middlewares") else []:
        if isinstance(middleware, SessionAuthMiddleware):
            return middleware
    # Walk the app state instead (stored at startup)
    return getattr(request.app.state, "auth_middleware", None)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/") -> HTMLResponse:
    # Already logged in — bounce straight to the app
    if request.session.get("authenticated"):
        return RedirectResponse(url=next, status_code=302)

    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"next": next, "error": None},
    )


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = (form.get("password") or "")
    next_url = (form.get("next") or "/").strip() or "/"

    auth = request.app.state.auth_middleware
    if auth and auth.verify(username, password):
        request.session["authenticated"] = True
        request.session["username"] = username
        return RedirectResponse(url=next_url, status_code=303)

    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"next": next_url, "error": "Invalid username or password."},
        status_code=401,
    )


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
