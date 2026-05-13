"""Email pattern generation and SMTP probing for domain enrichment.

Given a domain and optional contact names, generates candidate email addresses
and verifies them via SMTP RCPT TO probing — no message is ever sent.

Limitations
-----------
- Catch-all servers accept every RCPT TO: these are flagged as CATCH_ALL.
- Many ISPs block outbound port 25; in that case probe_domain returns [].
- Best-effort: not all valid addresses can be confirmed.
"""
from __future__ import annotations

import logging
import re
import smtplib
import socket
from dataclasses import dataclass

import dns.resolver

from src.models.enums import EmailStatus

log = logging.getLogger(__name__)

# Free/consumer mail domains — not worth probing
FREE_DOMAINS: frozenset[str] = frozenset([
    "gmail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "hotmail.co.uk",
    "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "mac.com",
    "aol.com", "protonmail.com", "proton.me", "zoho.com",
])

# Generic prefixes tried on every domain (in priority order)
GENERIC_PREFIXES = [
    "info", "office", "contact", "hello", "reception",
    "appointments", "front", "admin",
]

# Name-pattern templates — {first}, {last}, {fi} (first initial)
CONTACT_PATTERNS = [
    "{first}.{last}",
    "{fi}{last}",
    "dr{last}",
    "dr.{last}",
    "{first}",
    "dr{first}",
]


@dataclass
class ProbeResult:
    address: str
    status: EmailStatus  # VALID or CATCH_ALL
    catch_all: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    """Lowercase, ASCII-only, letters only."""
    return re.sub(r"[^a-z]", "", s.lower().strip())


def _generate_candidates(domain: str, contacts: list[tuple[str, str]]) -> list[str]:
    """Build a deduplicated list of candidate addresses."""
    seen: set[str] = set()
    out: list[str] = []

    def _add(addr: str) -> None:
        if addr not in seen:
            seen.add(addr)
            out.append(addr)

    # Generic first so they appear early in the probe order
    for prefix in GENERIC_PREFIXES:
        _add(f"{prefix}@{domain}")

    # Contact-based patterns
    for first_raw, last_raw in contacts:
        first = _slug(first_raw)
        last = _slug(last_raw)
        fi = first[:1]
        if not first and not last:
            continue
        for pattern in CONTACT_PATTERNS:
            try:
                addr = pattern.format(first=first, last=last, fi=fi) + f"@{domain}"
                if first or last:  # skip empty-slug combos
                    _add(addr)
            except KeyError:
                pass

    return out


def get_mx_host(domain: str, timeout: float = 5.0) -> str | None:
    """Return the highest-priority MX hostname for *domain*, or None on failure."""
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        answers = resolver.resolve(domain, "MX")
        best = sorted(answers, key=lambda r: r.preference)[0]
        return str(best.exchange).rstrip(".")
    except Exception as exc:
        log.debug("MX lookup failed for %s: %s", domain, exc)
        return None


def _smtp_session(mx_host: str, *addresses: str, timeout: float) -> dict[str, str]:
    """Open one SMTP session and probe multiple addresses.

    Returns a dict mapping address → 'valid' | 'invalid' | 'catch_all' | 'error'.
    A single 'error' key is set if the connection itself fails.
    """
    results: dict[str, str] = {}
    try:
        with smtplib.SMTP(mx_host, 25, timeout=timeout) as smtp:
            smtp.ehlo("probe.local")
            smtp.mail("")

            # Catch-all detection: probe an address that cannot exist
            domain = addresses[0].split("@")[1] if addresses else ""
            canary = f"canary_xzqq_99999@{domain}"
            canary_code, _ = smtp.rcpt(canary)
            if canary_code == 250:
                # Server accepts everything
                for addr in addresses:
                    results[addr] = "catch_all"
                return results

            for addr in addresses:
                try:
                    code, _ = smtp.rcpt(addr)
                    results[addr] = "valid" if code == 250 else "invalid"
                except smtplib.SMTPException as exc:
                    log.debug("RCPT failed for %s: %s", addr, exc)
                    results[addr] = "error"

    except (smtplib.SMTPException, socket.error, OSError, TimeoutError) as exc:
        log.debug("SMTP connection to %s failed: %s", mx_host, exc)
        results["_connection_error"] = str(exc)

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def probe_domain(
    domain: str,
    contacts: list[tuple[str, str]],
    smtp_timeout: float = 10.0,
    dns_timeout: float = 5.0,
) -> list[ProbeResult]:
    """Probe *domain* for valid email addresses.

    Args:
        domain:       Bare domain, e.g. ``glenndental.com``.
        contacts:     List of ``(first_name, last_name)`` tuples from extraction.
        smtp_timeout: Per-connection SMTP timeout in seconds.
        dns_timeout:  DNS resolver lifetime in seconds.

    Returns:
        List of :class:`ProbeResult` for addresses confirmed VALID or CATCH_ALL.
        Returns ``[]`` if the domain has no MX record or port 25 is unreachable.
    """
    if not domain or domain in FREE_DOMAINS:
        log.debug("Skipping %s — free/missing domain", domain)
        return []

    mx_host = get_mx_host(domain, timeout=dns_timeout)
    if not mx_host:
        log.debug("No MX record for %s", domain)
        return []

    candidates = _generate_candidates(domain, contacts)
    if not candidates:
        return []

    log.debug("Probing %d candidates at %s via %s", len(candidates), domain, mx_host)

    smtp_results = _smtp_session(mx_host, *candidates, timeout=smtp_timeout)

    if "_connection_error" in smtp_results:
        log.info(
            "SMTP port 25 unreachable for %s (%s) — enrichment skipped for domain",
            domain, smtp_results["_connection_error"],
        )
        return []

    out: list[ProbeResult] = []
    catch_all = any(v == "catch_all" for v in smtp_results.values())

    for addr in candidates:
        outcome = smtp_results.get(addr, "error")
        if outcome == "valid":
            out.append(ProbeResult(address=addr, status=EmailStatus.VALID))
        elif outcome == "catch_all":
            out.append(ProbeResult(address=addr, status=EmailStatus.CATCH_ALL, catch_all=True))
            if catch_all:
                # Only return the first few catch-all guesses — no point listing all
                if len(out) >= 3:
                    break

    return out
