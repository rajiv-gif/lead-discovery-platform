"""HTTP Basic Auth middleware for the dashboard.

Enabled when both DASHBOARD_USERNAME and DASHBOARD_PASSWORD are set in the
environment. If either is unset, all requests pass through unauthenticated
(safe for local use behind 127.0.0.1).

The /healthz endpoint is always exempt so Railway's health checks work
without credentials.
"""
from __future__ import annotations

import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_EXEMPT_PATHS = {"/healthz"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Require HTTP Basic Auth on all routes except exempt paths."""

    def __init__(self, app, username: str, password: str) -> None:
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                username, _, password = decoded.partition(":")
                user_ok = secrets.compare_digest(username, self._username)
                pass_ok = secrets.compare_digest(password, self._password)
                if user_ok and pass_ok:
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Lead Discovery Dashboard"'},
        )
