"""Unit tests for src/scraper/persist.py.

Uses pytest tmp_path for disk artifacts and MagicMock for the SQLAlchemy session.
No live DB required.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.enums import PageType
from src.scraper.fetcher import FetchResult
from src.scraper.persist import save_page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_result(
    html: str = "<html><body><p>Hello world dental practice.</p></body></html>",
    status_code: int = 200,
    url: str = "https://example.com/",
    final_url: str = "https://example.com/",
    content_type: str = "text/html",
) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=final_url,
        html=html,
        status_code=status_code,
        content_type=content_type,
    )


def make_session(existing=None) -> MagicMock:
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = existing
    return session


# ---------------------------------------------------------------------------
# save_page — creation
# ---------------------------------------------------------------------------


def test_save_page_creates_new_row(tmp_path):
    session = make_session(existing=None)
    company_id = uuid.uuid4()
    result = make_result()

    page, created = save_page(
        session=session,
        company_id=company_id,
        result=result,
        page_type=PageType.HOMEPAGE,
        pages_dir=tmp_path,
    )

    assert created is True
    session.add.assert_called_once()
    session.flush.assert_called_once()


def test_save_page_new_row_has_correct_fields(tmp_path):
    session = make_session(existing=None)
    company_id = uuid.uuid4()
    result = make_result(url="https://example.com/about", final_url="https://example.com/about/")

    page, _ = save_page(
        session=session,
        company_id=company_id,
        result=result,
        page_type=PageType.ABOUT,
        pages_dir=tmp_path,
    )

    added = session.add.call_args[0][0]
    assert added.company_id == company_id
    assert added.page_type == PageType.ABOUT
    assert added.http_status_code == 200
    assert added.content_type == "text/html"


def test_save_page_writes_html_file_to_disk(tmp_path):
    session = make_session(existing=None)
    html = "<html><body><p>Dental content.</p></body></html>"
    result = make_result(html=html)
    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

    save_page(
        session=session,
        company_id=uuid.uuid4(),
        result=result,
        page_type=PageType.HOMEPAGE,
        pages_dir=tmp_path,
    )

    html_file = tmp_path / f"{content_hash}.html"
    assert html_file.exists()
    assert html_file.read_text() == html


def test_save_page_writes_txt_artifact_to_disk(tmp_path):
    """extracted_text_path .txt file must be written when text is extracted."""
    session = make_session(existing=None)
    html = "<html><body><p>We are a dental practice providing excellent care.</p></body></html>"
    result = make_result(html=html)

    with patch("src.scraper.persist.extract_text", return_value="extracted plain text"):
        save_page(
            session=session,
            company_id=uuid.uuid4(),
            result=result,
            page_type=PageType.HOMEPAGE,
            pages_dir=tmp_path,
        )

    txt_files = list(tmp_path.glob("*.txt"))
    assert len(txt_files) == 1
    assert txt_files[0].read_text() == "extracted plain text"


def test_save_page_stores_extracted_text_in_db(tmp_path):
    """extracted_text must be set on the ORM object (for DB storage)."""
    session = make_session(existing=None)

    with patch("src.scraper.persist.extract_text", return_value="some extracted text"):
        save_page(
            session=session,
            company_id=uuid.uuid4(),
            result=make_result(),
            page_type=PageType.HOMEPAGE,
            pages_dir=tmp_path,
        )

    added = session.add.call_args[0][0]
    assert added.extracted_text == "some extracted text"


def test_save_page_stores_word_count_in_db(tmp_path):
    session = make_session(existing=None)

    with patch("src.scraper.persist.extract_text", return_value="one two three"):
        with patch("src.scraper.persist.count_words", return_value=3):
            save_page(
                session=session,
                company_id=uuid.uuid4(),
                result=make_result(),
                page_type=PageType.HOMEPAGE,
                pages_dir=tmp_path,
            )

    added = session.add.call_args[0][0]
    assert added.word_count == 3


# ---------------------------------------------------------------------------
# save_page — dedup
# ---------------------------------------------------------------------------


def test_save_page_returns_existing_when_same_hash(tmp_path):
    existing = MagicMock()
    session = make_session(existing=existing)

    page, created = save_page(
        session=session,
        company_id=uuid.uuid4(),
        result=make_result(),
        page_type=PageType.HOMEPAGE,
        pages_dir=tmp_path,
    )

    assert created is False
    assert page is existing
    session.add.assert_not_called()


def test_save_page_creates_new_row_when_hash_differs(tmp_path):
    """If URL matches but hash differs, a new row is inserted."""
    session = make_session(existing=None)  # dedup query returns None (different hash)

    page, created = save_page(
        session=session,
        company_id=uuid.uuid4(),
        result=make_result(html="<html>new content</html>"),
        page_type=PageType.HOMEPAGE,
        pages_dir=tmp_path,
    )

    assert created is True
    session.add.assert_called_once()


# ---------------------------------------------------------------------------
# save_page — failed fetch (empty html)
# ---------------------------------------------------------------------------


def test_save_page_handles_empty_html_for_failed_fetch(tmp_path):
    """Even failed fetches (no html) must create a row."""
    session = make_session(existing=None)
    result = FetchResult(
        url="https://example.com/",
        final_url="https://example.com/",
        html="",
        status_code=404,
        error="HTTP 404",
    )

    page, created = save_page(
        session=session,
        company_id=uuid.uuid4(),
        result=result,
        page_type=None,
        pages_dir=tmp_path,
    )

    assert created is True
    added = session.add.call_args[0][0]
    assert added.http_status_code == 404
    assert added.content_hash is None
