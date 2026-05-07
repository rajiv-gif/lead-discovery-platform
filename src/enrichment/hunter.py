"""Hunter.io API client for email discovery.

Finds real email addresses associated with a company domain from Hunter's
database of publicly indexed emails.  Two endpoints are used:

  domain_search  — returns all emails Hunter knows for a domain, including
                   type (personal vs generic), confidence score, and the
                   person's name when available.

  email_finder   — looks up a specific person's email given their name and
                   domain.  Used when the extract stage found a contact name
                   but no email.

Both methods return empty results (never raise) when the API key is absent,
the domain has no data, or the monthly quota is exhausted — so the enrichment
stage degrades gracefully without a Hunter subscription.

Pricing reference (as of 2025):
  Free   — 25 searches / month
  Starter — $49 / mo for 500 searches
  Growth  — $99 / mo for 2 500 searches
Sign up at https://hunter.io
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_BASE = "https://api.hunter.io/v2"
_TIMEOUT = 15.0


@dataclass
class HunterEmail:
    """A single email result from Hunter."""
    address: str
    email_type: str          # "personal" or "generic"
    confidence: int          # 0–100
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    position: Optional[str] = None
    linkedin_url: Optional[str] = None
    sources: list[str] = field(default_factory=list)


class HunterClient:
    """Thin wrapper around the Hunter.io v2 REST API.

    Args:
        api_key: Hunter API key (from https://hunter.io/api-keys).
        min_confidence: Only return emails with confidence ≥ this value (0–100).
                        Hunter considers 90+ reliable, 70+ usable. Default 70.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        min_confidence: int = 70,
        timeout: float = _TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._min_confidence = min_confidence
        self._timeout = timeout

    def domain_search(
        self,
        domain: str,
        limit: int = 10,
    ) -> list[HunterEmail]:
        """Return all emails Hunter knows for *domain*.

        Args:
            domain: Bare domain, e.g. ``"acme.com"`` (no scheme/path).
            limit:  Maximum results to return (Hunter caps at 100).

        Returns:
            List of ``HunterEmail`` objects filtered by ``min_confidence``.
            Empty list on any error or quota exhaustion.
        """
        try:
            resp = httpx.get(
                f"{_BASE}/domain-search",
                params={
                    "domain": domain,
                    "api_key": self._api_key,
                    "limit": min(limit, 100),
                },
                timeout=self._timeout,
            )
        except Exception as exc:
            log.warning("Hunter domain_search network error for %r: %s", domain, exc)
            return []

        if resp.status_code == 401:
            log.warning("Hunter API key invalid or expired")
            return []
        if resp.status_code == 429:
            log.warning("Hunter monthly quota exhausted — skipping enrichment")
            return []
        if not resp.is_success:
            log.warning("Hunter domain_search HTTP %d for %r", resp.status_code, domain)
            return []

        try:
            data = resp.json()
        except Exception as exc:
            log.warning("Hunter domain_search bad JSON for %r: %s", domain, exc)
            return []

        emails: list[HunterEmail] = []
        for item in (data.get("data") or {}).get("emails") or []:
            address = (item.get("value") or "").strip().lower()
            if not address:
                continue
            confidence = item.get("confidence") or 0
            if confidence < self._min_confidence:
                continue
            emails.append(HunterEmail(
                address=address,
                email_type=item.get("type") or "generic",
                confidence=confidence,
                first_name=item.get("first_name") or None,
                last_name=item.get("last_name") or None,
                position=item.get("position") or None,
                linkedin_url=item.get("linkedin") or None,
                sources=[s.get("uri", "") for s in (item.get("sources") or [])],
            ))

        log.debug(
            "Hunter domain_search %r → %d emails (≥%d confidence)",
            domain, len(emails), self._min_confidence,
        )
        return emails

    def email_finder(
        self,
        domain: str,
        first_name: str,
        last_name: str,
    ) -> Optional[HunterEmail]:
        """Find a specific person's email at *domain*.

        Returns a ``HunterEmail`` if Hunter found a match above ``min_confidence``,
        otherwise None.
        """
        if not first_name and not last_name:
            return None

        try:
            resp = httpx.get(
                f"{_BASE}/email-finder",
                params={
                    "domain": domain,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_key": self._api_key,
                },
                timeout=self._timeout,
            )
        except Exception as exc:
            log.warning(
                "Hunter email_finder network error for %r %s %s: %s",
                domain, first_name, last_name, exc,
            )
            return None

        if resp.status_code in (401, 429):
            return None
        if not resp.is_success:
            return None

        try:
            data = resp.json().get("data") or {}
        except Exception:
            return None

        address = (data.get("email") or "").strip().lower()
        confidence = data.get("score") or 0
        if not address or confidence < self._min_confidence:
            return None

        return HunterEmail(
            address=address,
            email_type="personal",
            confidence=confidence,
            first_name=data.get("first_name") or first_name or None,
            last_name=data.get("last_name") or last_name or None,
            position=data.get("position") or None,
            linkedin_url=data.get("linkedin") or None,
        )
