"""Tests for src/verification/email_verifier.py"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import dns.exception
import dns.resolver
import pytest

from src.models.enums import EmailStatus
from src.verification.email_verifier import verify_email


# ---------------------------------------------------------------------------
# Valid format + valid MX
# ---------------------------------------------------------------------------


@patch("src.verification.email_verifier.dns.resolver.Resolver")
def test_valid_format_valid_mx(mock_resolver_cls):
    mock_resolver = MagicMock()
    mock_resolver.resolve.return_value = [MagicMock()]  # 1 MX record
    mock_resolver_cls.return_value = mock_resolver

    status, mx_valid = verify_email("user@example.com")
    assert status == EmailStatus.VALID
    assert mx_valid is True


# ---------------------------------------------------------------------------
# Valid format + no MX (NoAnswer)
# ---------------------------------------------------------------------------


@patch("src.verification.email_verifier.dns.resolver.Resolver")
def test_valid_format_no_answer(mock_resolver_cls):
    mock_resolver = MagicMock()
    mock_resolver.resolve.side_effect = dns.resolver.NoAnswer
    mock_resolver_cls.return_value = mock_resolver

    status, mx_valid = verify_email("user@example.com")
    assert status == EmailStatus.INVALID
    assert mx_valid is False


# ---------------------------------------------------------------------------
# Valid format + NXDOMAIN
# ---------------------------------------------------------------------------


@patch("src.verification.email_verifier.dns.resolver.Resolver")
def test_valid_format_nxdomain(mock_resolver_cls):
    mock_resolver = MagicMock()
    mock_resolver.resolve.side_effect = dns.resolver.NXDOMAIN
    mock_resolver_cls.return_value = mock_resolver

    status, mx_valid = verify_email("user@nonexistent.tld")
    assert status == EmailStatus.INVALID
    assert mx_valid is False


# ---------------------------------------------------------------------------
# Valid format + DNS timeout (other DNSException)
# ---------------------------------------------------------------------------


@patch("src.verification.email_verifier.dns.resolver.Resolver")
def test_valid_format_dns_timeout(mock_resolver_cls):
    mock_resolver = MagicMock()
    mock_resolver.resolve.side_effect = dns.exception.Timeout
    mock_resolver_cls.return_value = mock_resolver

    status, mx_valid = verify_email("user@example.com")
    assert status == EmailStatus.RISKY
    assert mx_valid is False


# ---------------------------------------------------------------------------
# Invalid format — no @
# ---------------------------------------------------------------------------


def test_invalid_format_no_at():
    status, mx_valid = verify_email("userexample.com")
    assert status == EmailStatus.INVALID
    assert mx_valid is False


# ---------------------------------------------------------------------------
# Invalid format — no TLD
# ---------------------------------------------------------------------------


def test_invalid_format_no_tld():
    status, mx_valid = verify_email("user@example")
    assert status == EmailStatus.INVALID
    assert mx_valid is False


# ---------------------------------------------------------------------------
# Invalid format — empty string
# ---------------------------------------------------------------------------


def test_invalid_format_empty():
    status, mx_valid = verify_email("")
    assert status == EmailStatus.INVALID
    assert mx_valid is False


# ---------------------------------------------------------------------------
# Valid format + generic DNSException → RISKY
# ---------------------------------------------------------------------------


@patch("src.verification.email_verifier.dns.resolver.Resolver")
def test_valid_format_generic_dns_exception(mock_resolver_cls):
    mock_resolver = MagicMock()
    mock_resolver.resolve.side_effect = dns.exception.DNSException("lookup failed")
    mock_resolver_cls.return_value = mock_resolver

    status, mx_valid = verify_email("user@example.com")
    assert status == EmailStatus.RISKY
    assert mx_valid is False


# ---------------------------------------------------------------------------
# DNS timeout is set on resolver
# ---------------------------------------------------------------------------


@patch("src.verification.email_verifier.dns.resolver.Resolver")
def test_dns_timeout_is_applied(mock_resolver_cls):
    mock_resolver = MagicMock()
    mock_resolver.resolve.return_value = [MagicMock()]
    mock_resolver_cls.return_value = mock_resolver

    verify_email("user@example.com", dns_timeout=3.0)
    assert mock_resolver.lifetime == 3.0
