"""HTTP fetcher for the scraping stage.

Responsibilities:
  - Robots.txt compliance (fail-open: log WARNING and proceed if robots.txt is
    unreachable or unparseable).
  - Per-domain rate limiting (configurable delay between requests to same host).
  - Single HTTP GET with configurable timeouts; no retry logic (caller decides
    what to do with non-200 responses).
  - Returns a ``FetchResult`` dataclass — never raises on HTTP errors.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from src.config.settings import settings

log = logging.getLogger(__name__)

_USER_AGENT = "LeadDiscoveryBot/1.0 (+https://example.com/bot)"


# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """The outcome of a single HTTP GET request.

    ``html`` is the response body text (empty string on error).
    ``status_code`` is None when a network-level error occurs.
    ``error`` holds the exception message when fetching failed.
    ``content_type`` is the HTTP Content-Type header value (or None).
    ``final_url`` is the URL after following all redirects.
    ``content_hash`` is the SHA-256 hex digest of ``html`` (or None if empty).
    """

    url: str
    final_url: str
    html: str
    status_code: Optional[int]
    content_type: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when fetch succeeded and returned a 200-level status."""
        return self.status_code is not None and 200 <= self.status_code < 300

    @property
    def content_hash(self) -> Optional[str]:
        if not self.html:
            return None
        return hashlib.sha256(self.html.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# RobotCache — fail-open robots.txt compliance
# ---------------------------------------------------------------------------


class RobotCache:
    """Per-domain robots.txt cache.

    If the robots.txt fetch or parse fails for any reason, the domain is treated
    as fully allowed and a WARNING is logged (fail-open behaviour).
    """

    def __init__(self, user_agent: str = _USER_AGENT) -> None:
        self._user_agent = user_agent
        self._cache: dict[str, RobotFileParser] = {}

    def _load(self, scheme: str, host: str) -> RobotFileParser:
        robots_url = f"{scheme}://{host}/robots.txt"
        parser = RobotFileParser(robots_url)
        try:
            parser.read()
        except Exception as exc:
            log.warning(
                "robots.txt fetch/parse failed for %s — treating as allow-all. Error: %s",
                host,
                exc,
            )
            # Build a permissive parser that allows everything
            parser = RobotFileParser()
            parser.parse(["User-agent: *", "Allow: /"])
        return parser

    def is_allowed(self, url: str) -> bool:
        """Return True if *url* is allowed for our user-agent."""
        parsed = urlparse(url)
        host = parsed.hostname or ""
        scheme = parsed.scheme.lower()
        if not host:
            return True
        if host not in self._cache:
            self._cache[host] = self._load(scheme, host)
        return self._cache[host].can_fetch(self._user_agent, url)


# ---------------------------------------------------------------------------
# DomainRateLimiter
# ---------------------------------------------------------------------------


class DomainRateLimiter:
    """Tracks last-fetch timestamp per domain and enforces a minimum delay."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay = delay_seconds
        self._last_fetch: dict[str, float] = {}

    def wait(self, url: str) -> None:
        """Sleep if necessary to honour the per-domain rate limit."""
        host = urlparse(url).hostname or url
        last = self._last_fetch.get(host, 0.0)
        elapsed = time.monotonic() - last
        remaining = self._delay - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_fetch[host] = time.monotonic()


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class Fetcher:
    """Synchronous HTTP fetcher with robots.txt compliance and rate limiting.

    Args:
        rate_limit_delay: Minimum seconds between fetches to the same domain.
        connect_timeout:  Connection timeout in seconds.
        read_timeout:     Read timeout in seconds.
        robot_cache:      Shared ``RobotCache`` instance (created if not given).
    """

    def __init__(
        self,
        rate_limit_delay: Optional[float] = None,
        connect_timeout: Optional[float] = None,
        read_timeout: Optional[float] = None,
        robot_cache: Optional[RobotCache] = None,
    ) -> None:
        self._rate_limiter = DomainRateLimiter(
            rate_limit_delay
            if rate_limit_delay is not None
            else settings.scraper_rate_limit_delay
        )
        self._connect_timeout = (
            connect_timeout
            if connect_timeout is not None
            else settings.scraper_connect_timeout
        )
        self._read_timeout = (
            read_timeout
            if read_timeout is not None
            else settings.scraper_read_timeout
        )
        self._robots = robot_cache if robot_cache is not None else RobotCache()

    def fetch(self, url: str) -> FetchResult:
        """Fetch *url* and return a ``FetchResult``.

        Returns a result with ``ok=False`` and ``error`` set if:
        - robots.txt disallows the URL
        - The HTTP request raises a network-level exception

        Never raises; all errors are captured in the returned object.
        """
        # Robots.txt check
        if not self._robots.is_allowed(url):
            log.info("robots.txt disallows %r — skipping", url)
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=None,
                error="disallowed by robots.txt",
            )

        # Rate limiting
        self._rate_limiter.wait(url)

        # HTTP GET
        timeout = httpx.Timeout(connect=self._connect_timeout, read=self._read_timeout,
                                write=5.0, pool=5.0)
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
                follow_redirects=True,
            )
        except Exception as exc:
            log.warning("fetch error for %r: %s", url, exc)
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=None,
                error=str(exc),
            )

        content_type = response.headers.get("content-type")
        final_url = str(response.url)

        if not (200 <= response.status_code < 300):
            log.debug("non-2xx status %d for %r", response.status_code, url)
            return FetchResult(
                url=url,
                final_url=final_url,
                html="",
                status_code=response.status_code,
                content_type=content_type,
                error=f"HTTP {response.status_code}",
            )

        try:
            html = response.text
        except Exception as exc:
            log.warning("decoding error for %r: %s", url, exc)
            return FetchResult(
                url=url,
                final_url=final_url,
                html="",
                status_code=response.status_code,
                content_type=content_type,
                error=f"decode error: {exc}",
            )

        log.debug("fetched %r → %d bytes", url, len(html))
        return FetchResult(
            url=url,
            final_url=final_url,
            html=html,
            status_code=response.status_code,
            content_type=content_type,
        )
