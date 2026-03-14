"""Website reachability check via HTTP HEAD + GET fallback."""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


def check_website(url: str, timeout: float = 10.0) -> bool:
    """Return True if the website at *url* is reachable.

    Strategy:
    1. Try ``HEAD`` first (cheap — no body download).
    2. If HEAD fails (any exception) or returns non-2xx, fall back to ``GET``.
    3. Return True only when a 2xx response is received.

    Never raises; all exceptions are caught and logged at DEBUG level.
    """
    # --- HEAD attempt ---
    try:
        response = httpx.head(url, follow_redirects=True, timeout=timeout)
        if response.is_success:
            return True
        log.debug("HEAD %s returned %s — falling back to GET", url, response.status_code)
    except Exception as exc:
        log.debug("HEAD %s failed: %s — falling back to GET", url, exc)

    # --- GET fallback ---
    try:
        response = httpx.get(url, follow_redirects=True, timeout=timeout)
        if response.is_success:
            return True
        log.debug("GET %s returned %s", url, response.status_code)
        return False
    except Exception as exc:
        log.debug("GET %s failed: %s", url, exc)
        return False
