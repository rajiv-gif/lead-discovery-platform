"""Unit tests for src/scraper/runner.py.

Uses MagicMock for DB session and Fetcher — no live network or DB.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.models.enums import DiscoveryHitStatus, PageType
from src.scraper.fetcher import FetchResult
from src.scraper.runner import ScrapeSummary, _scrape_hit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_hit(status=DiscoveryHitStatus.PENDING) -> MagicMock:
    hit = MagicMock()
    hit.id = uuid.uuid4()
    hit.status = status
    hit.company_id = uuid.uuid4()
    hit.error_message = None
    return hit


def make_company(website: str | None = "https://example.com/") -> MagicMock:
    company = MagicMock()
    company.id = uuid.uuid4()
    company.website = website
    return company


def ok_result(url: str = "https://example.com/", html: str = "<html><body>Content</body></html>") -> FetchResult:
    return FetchResult(url=url, final_url=url, html=html, status_code=200)


def failed_result(url: str = "https://example.com/") -> FetchResult:
    return FetchResult(url=url, final_url=url, html="", status_code=None, error="timeout")


def make_session() -> MagicMock:
    session = MagicMock()
    # save_page dedup check: always returns None (new page)
    session.execute.return_value.scalar_one_or_none.return_value = None
    return session


def make_fetcher(homepage_result: FetchResult, sup_result: FetchResult | None = None) -> MagicMock:
    fetcher = MagicMock()
    if sup_result is None:
        sup_result = FetchResult(
            url="https://example.com/about", final_url="https://example.com/about",
            html="<html><body>About page</body></html>", status_code=200
        )
    # First call → homepage, subsequent calls → supplemental
    fetcher.fetch.side_effect = [homepage_result] + [sup_result] * 5
    return fetcher


# ---------------------------------------------------------------------------
# _scrape_hit — status transitions
# ---------------------------------------------------------------------------


def test_scrape_hit_sets_scraped_on_success(tmp_path):
    summary = ScrapeSummary()
    session = make_session()
    hit = make_hit()
    company = make_company()
    fetcher = make_fetcher(ok_result())

    with patch("src.scraper.runner.save_page", return_value=(MagicMock(), True)):
        with patch("src.scraper.runner.find_supplemental_urls", return_value={}):
            _scrape_hit(session, hit, company, fetcher, summary)

    assert hit.status == DiscoveryHitStatus.SCRAPED
    assert summary.hits_scraped == 1
    assert summary.hits_failed == 0


def test_scrape_hit_sets_failed_when_homepage_fetch_fails(tmp_path):
    summary = ScrapeSummary()
    session = make_session()
    hit = make_hit()
    company = make_company()
    fetcher = make_fetcher(failed_result())

    _scrape_hit(session, hit, company, fetcher, summary)

    assert hit.status == DiscoveryHitStatus.FAILED
    assert hit.error_message is not None
    assert summary.hits_failed == 1
    assert summary.hits_scraped == 0


def test_scrape_hit_sets_skipped_when_no_website():
    summary = ScrapeSummary()
    session = make_session()
    hit = make_hit()
    company = make_company(website=None)
    fetcher = MagicMock()

    _scrape_hit(session, hit, company, fetcher, summary)

    assert hit.status == DiscoveryHitStatus.SKIPPED
    assert summary.hits_skipped == 1
    fetcher.fetch.assert_not_called()


def test_scrape_hit_counts_saved_pages():
    summary = ScrapeSummary()
    session = make_session()
    hit = make_hit()
    company = make_company()

    # homepage + 2 supplemental pages; fetcher provides 3 responses
    fetcher = MagicMock()
    fetcher.fetch.side_effect = [
        ok_result(),
        ok_result("https://example.com/about"),
        ok_result("https://example.com/contact"),
    ]

    # homepage=new, about=new, contact=dedup
    save_results = [(MagicMock(), True), (MagicMock(), True), (MagicMock(), False)]
    call_index = [0]

    def fake_save(*args, **kwargs):
        idx = call_index[0]
        call_index[0] += 1
        return save_results[idx] if idx < len(save_results) else (MagicMock(), False)

    with patch("src.scraper.runner.save_page", side_effect=fake_save):
        with patch("src.scraper.runner.find_supplemental_urls",
                   return_value={
                       PageType.ABOUT: "https://example.com/about",
                       PageType.CONTACT: "https://example.com/contact",
                   }):
            _scrape_hit(session, hit, company, fetcher, summary)

    assert summary.pages_saved == 2    # two created=True
    assert summary.pages_deduplicated == 1  # one created=False


def test_scrape_hit_partial_supplemental_does_not_fail_hit():
    """Supplemental page fetch failure must not change hit to failed."""
    summary = ScrapeSummary()
    session = make_session()
    hit = make_hit()
    company = make_company()

    # Homepage OK, supplemental fetch fails
    fetcher = MagicMock()
    fetcher.fetch.side_effect = [
        ok_result(),
        failed_result("https://example.com/about"),
    ]

    with patch("src.scraper.runner.save_page", return_value=(MagicMock(), True)):
        with patch("src.scraper.runner.find_supplemental_urls",
                   return_value={PageType.ABOUT: "https://example.com/about"}):
            _scrape_hit(session, hit, company, fetcher, summary)

    # Hit still scraped despite supplemental failure
    assert hit.status == DiscoveryHitStatus.SCRAPED
    assert summary.hits_failed == 0


# ---------------------------------------------------------------------------
# ScrapeSummary
# ---------------------------------------------------------------------------


def test_scrape_summary_record_error():
    s = ScrapeSummary()
    s.record_error("hit=abc: timeout")
    assert s.errors == 1
    assert "timeout" in s.error_details[0]


def test_scrape_summary_initial_values():
    s = ScrapeSummary()
    assert s.hits_scraped == 0
    assert s.hits_skipped == 0
    assert s.hits_failed == 0
    assert s.pages_saved == 0
    assert s.pages_deduplicated == 0
    assert s.errors == 0
    assert s.error_details == []
