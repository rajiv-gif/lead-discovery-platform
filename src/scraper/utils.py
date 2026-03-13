"""Scraper utility helpers."""
from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Return a canonical form of *url* suitable for dedup comparisons.

    Transformations applied:
    - Lowercase scheme and host.
    - Strip default ports (80 for http, 443 for https).
    - Strip query string and fragment.
    - Strip trailing slash from non-root paths (root "/" is kept).

    Examples::

        normalize_url("HTTPS://Example.com/About/") == "https://example.com/about"
        normalize_url("http://example.com:80/")     == "http://example.com/"
        normalize_url("https://x.com/p?q=1#h")      == "https://x.com/p"
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    port = parsed.port

    # Drop default ports
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    netloc = host if port is None else f"{host}:{port}"

    path = parsed.path
    # Strip trailing slash from non-root paths
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse((scheme, netloc, path, "", "", ""))
