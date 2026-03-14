"""Email verification: format check + MX record DNS lookup."""
from __future__ import annotations

import logging
import re

import dns.exception
import dns.resolver

from src.models.enums import EmailStatus

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def verify_email(address: str, dns_timeout: float = 5.0) -> tuple[EmailStatus, bool]:
    """Verify an email address by format and MX record lookup.

    Returns a ``(status, mx_valid)`` tuple:
      - ``(VALID, True)``    — format OK, ≥1 MX record found
      - ``(INVALID, False)`` — format fail, NXDOMAIN, or NoAnswer
      - ``(RISKY, False)``   — format OK but transient DNS error
    """
    # --- Format check ---
    if not _EMAIL_RE.match(address):
        return (EmailStatus.INVALID, False)

    domain = address.split("@", 1)[1]

    # --- MX lookup ---
    resolver = dns.resolver.Resolver()
    resolver.lifetime = dns_timeout

    try:
        answers = resolver.resolve(domain, "MX")
        if answers:
            return (EmailStatus.VALID, True)
        # Empty answer set — treat as no MX
        return (EmailStatus.INVALID, False)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return (EmailStatus.INVALID, False)
    except dns.exception.DNSException as exc:
        log.warning("DNS error for domain %r: %s", domain, exc)
        return (EmailStatus.RISKY, False)
