"""Unit tests for src/scraper/classifier.py."""
from __future__ import annotations

import pytest

from src.models.enums import PageType
from src.scraper.classifier import classify_page, classify_url


# ---------------------------------------------------------------------------
# classify_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://example.com/",
    "https://example.com",
])
def test_classify_url_homepage(url):
    assert classify_url(url) == PageType.HOMEPAGE


@pytest.mark.parametrize("url", [
    "https://example.com/about",
    "https://example.com/about-us",
    "https://example.com/about_us",
    "https://example.com/who-we-are",
    "https://example.com/our-story",
    "https://example.com/the-practice",
])
def test_classify_url_about(url):
    assert classify_url(url) == PageType.ABOUT


@pytest.mark.parametrize("url", [
    "https://example.com/contact",
    "https://example.com/contact-us",
    "https://example.com/get-in-touch",
    "https://example.com/appointments",
    "https://example.com/book-an-appointment",
    "https://example.com/location",
    "https://example.com/find-us",
])
def test_classify_url_contact(url):
    assert classify_url(url) == PageType.CONTACT


@pytest.mark.parametrize("url", [
    "https://example.com/team",
    "https://example.com/staff",
    "https://example.com/our-dentists",
    "https://example.com/meet-the-team",
])
def test_classify_url_team(url):
    assert classify_url(url) == PageType.TEAM


@pytest.mark.parametrize("url", [
    "https://example.com/services",
    "https://example.com/treatments",
    "https://example.com/dental-care",
    "https://example.com/implants",
    "https://example.com/orthodontics",
])
def test_classify_url_services(url):
    assert classify_url(url) == PageType.SERVICES


def test_classify_url_other_for_unknown_path():
    assert classify_url("https://example.com/some-random-page-xyz") == PageType.OTHER


# ---------------------------------------------------------------------------
# classify_page — title / h1 override for OTHER urls
# ---------------------------------------------------------------------------


def test_classify_page_uses_title_for_other_url():
    result = classify_page("https://example.com/xyz", title="About Our Practice", h1=None)
    assert result == PageType.ABOUT


def test_classify_page_uses_h1_for_other_url():
    result = classify_page("https://example.com/xyz", title=None, h1="Contact Us Today")
    assert result == PageType.CONTACT


def test_classify_page_url_wins_over_title():
    """URL classification takes precedence when it's not OTHER."""
    result = classify_page("https://example.com/team", title="Contact Us", h1=None)
    assert result == PageType.TEAM


def test_classify_page_returns_other_when_no_signals():
    result = classify_page("https://example.com/xyz", title=None, h1=None)
    assert result == PageType.OTHER


def test_classify_page_homepage_on_root():
    result = classify_page("https://example.com/", title="Welcome to Our Practice", h1="Home")
    assert result == PageType.HOMEPAGE
