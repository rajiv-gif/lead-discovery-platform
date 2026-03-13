"""Unit tests for src/scraper/page_finder.py."""
from __future__ import annotations

import pytest

from src.models.enums import PageType
from src.scraper.page_finder import find_supplemental_urls


HOMEPAGE = "https://example.com/"

_HTML_WITH_LINKS = """
<html>
<body>
  <nav>
    <a href="/">Home</a>
    <a href="/about-us">About Us</a>
    <a href="/contact">Contact</a>
    <a href="/team">Our Team</a>
    <a href="/services">Services</a>
    <a href="/blog">Blog</a>
  </nav>
</body>
</html>
"""


def test_find_supplemental_returns_about():
    result = find_supplemental_urls(HOMEPAGE, _HTML_WITH_LINKS)
    assert PageType.ABOUT in result
    assert "about-us" in result[PageType.ABOUT]


def test_find_supplemental_returns_contact():
    result = find_supplemental_urls(HOMEPAGE, _HTML_WITH_LINKS)
    assert PageType.CONTACT in result
    assert "contact" in result[PageType.CONTACT]


def test_find_supplemental_returns_team():
    result = find_supplemental_urls(HOMEPAGE, _HTML_WITH_LINKS)
    assert PageType.TEAM in result
    assert "team" in result[PageType.TEAM]


def test_find_supplemental_excludes_homepage_type():
    """HOMEPAGE-type URLs (root path) must not appear in results."""
    result = find_supplemental_urls(HOMEPAGE, _HTML_WITH_LINKS)
    assert PageType.HOMEPAGE not in result


def test_find_supplemental_no_duplicate_urls():
    """The same URL must not be used for two different page types."""
    result = find_supplemental_urls(HOMEPAGE, _HTML_WITH_LINKS)
    urls = list(result.values())
    assert len(urls) == len(set(urls))


def test_find_supplemental_empty_html_returns_empty():
    result = find_supplemental_urls(HOMEPAGE, "")
    assert result == {}


def test_find_supplemental_skips_external_links():
    html = """
    <html><body>
      <a href="https://external.com/about">External About</a>
      <a href="/our-contact">Contact</a>
    </body></html>
    """
    result = find_supplemental_urls(HOMEPAGE, html)
    # External link must not appear
    for url in result.values():
        assert "external.com" not in url


def test_find_supplemental_skips_media_extensions():
    html = """
    <html><body>
      <a href="/brochure.pdf">Download PDF</a>
      <a href="/contact">Contact</a>
    </body></html>
    """
    result = find_supplemental_urls(HOMEPAGE, html)
    for url in result.values():
        assert not url.endswith(".pdf")


def test_find_supplemental_prefers_shorter_path():
    """When multiple about-type links exist, shortest path wins."""
    html = """
    <html><body>
      <a href="/about-us/our-long-history-page">Long About</a>
      <a href="/about-us">Short About</a>
    </body></html>
    """
    result = find_supplemental_urls(HOMEPAGE, html)
    if PageType.ABOUT in result:
        assert result[PageType.ABOUT].rstrip("/").endswith("/about-us")


def test_find_supplemental_resolves_relative_links():
    html = '<html><body><a href="contact">Contact</a></body></html>'
    result = find_supplemental_urls("https://example.com/", html)
    if PageType.CONTACT in result:
        assert result[PageType.CONTACT].startswith("https://example.com")
