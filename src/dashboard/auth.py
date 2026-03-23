"""Session-based authentication for the dashboard.

How it works:
  1. SessionMiddleware (Starlette) signs a cookie with SESSION_SECRET_KEY.
  2. SessionAuthMiddleware checks request.session["authenticated"] on every
     request except exempt paths. Unauthenticated requests are redirected to
     /login?next=<original_path>.
  3. /login accepts POST with username + password, sets the session flag, then
     redirects to ?next or /.
  4. /logout clears the session and redirects to /login.

Env vars (all optional for local dev, required for Railway):
  DASHBOARD_USERNAME   — required to enforce credentials
  DASHBOARD_PASSWORD   — required to enforce credentials
  SESSION_SECRET_KEY   — secret used to sign the cookie (use a long random string)

If DASHBOARD_USERNAME or DASHBOARD_PASSWORD are unset, any submitted credentials
are accepted (useful for local dev without env setup).
"""
from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

# Paths that never require authentication
_EXEMPT = {"/login", "/healthz"}


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to /login."""

    def __init__(self, app, username: str | None, password: str | None) -> None:
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Always allow exempt paths
        if path in _EXEMPT:
            return await call_next(request)

        # Check session
        if request.session.get("authenticated"):
            return await call_next(request)

        # Not authenticated — redirect to login, preserving the intended path
        next_url = request.url.path
        if request.url.query:
            next_url = f"{next_url}?{request.url.query}"
        return RedirectResponse(url=f"/login?next={next_url}", status_code=302)

    def verify(self, username: str, password: str) -> bool:
        """Return True if credentials are valid."""
        if not self._username or not self._password:
            # No credentials configured — accept anything (dev mode)
            return True
        user_ok = secrets.compare_digest(username, self._username)
        pass_ok = secrets.compare_digest(password, self._password)
        return user_ok and pass_ok
