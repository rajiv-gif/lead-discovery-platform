"""Persist a scraped page to disk and PostgreSQL.

Dedup key: ``(company_id, normalized_url, content_hash)``

If a ``CompanyPage`` already exists with the same company_id + normalized_url
AND the same content_hash, the row is returned unchanged (no-op).

If the URL exists but the hash differs, a new row is inserted (content updated).

Disk artifacts written:
  - ``<pages_dir>/<hash>.html``   — raw HTML
  - ``<pages_dir>/<hash>.txt``    — extracted plain text (if non-empty)

The ``pages_dir`` is resolved from ``settings.pages_dir`` and created on
first write if it does not already exist.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.models.company_page import CompanyPage
from src.models.enums import PageType
from src.scraper.fetcher import FetchResult
from src.scraper.text_extractor import count_words, extract_text
from src.scraper.utils import normalize_url

log = logging.getLogger(__name__)


def save_page(
    session: Session,
    company_id: uuid.UUID,
    result: FetchResult,
    page_type: Optional[PageType],
    discovery_hit_id: Optional[uuid.UUID] = None,
    pages_dir: Optional[Path] = None,
) -> tuple[CompanyPage, bool]:
    """Persist *result* for *company_id*; return ``(page, created)``.

    Args:
        session:           Active SQLAlchemy session.
        company_id:        UUID of the owning ``Company``.
        result:            ``FetchResult`` from the fetcher.
        page_type:         Classified page type.
        discovery_hit_id:  Optional link back to the triggering ``DiscoveryHit``.
        pages_dir:         Override the pages directory (defaults to settings).

    Returns:
        ``(page, created)`` where ``created=False`` means an identical row
        already existed (same URL + same hash).
    """
    if pages_dir is None:
        pages_dir = settings.pages_dir
    pages_dir.mkdir(parents=True, exist_ok=True)

    norm_url = normalize_url(result.final_url or result.url)
    content_hash = result.content_hash  # None when html is empty

    # --- Dedup check ---
    existing: Optional[CompanyPage] = session.execute(
        select(CompanyPage).where(
            CompanyPage.company_id == company_id,
            CompanyPage.url == norm_url,
            CompanyPage.content_hash == content_hash,
        )
    ).scalar_one_or_none()

    if existing is not None:
        log.debug("page already persisted for company=%s url=%r hash=%s", company_id, norm_url, content_hash)
        return existing, False

    # --- Write HTML to disk ---
    if content_hash and result.html:
        html_path = pages_dir / f"{content_hash}.html"
        if not html_path.exists():
            html_path.write_text(result.html, encoding="utf-8", errors="replace")
        raw_html_path = str(html_path.relative_to(Path.cwd()) if html_path.is_relative_to(Path.cwd()) else html_path)
    else:
        # No HTML (failed fetch) — write an empty placeholder so the column is non-null
        placeholder_id = uuid.uuid4().hex
        html_path = pages_dir / f"{placeholder_id}.html"
        html_path.write_text("", encoding="utf-8")
        raw_html_path = str(html_path)

    # --- Extract text and write .txt artifact ---
    extracted_text: Optional[str] = None
    extracted_text_path: Optional[str] = None
    word_count: Optional[int] = None

    if result.html:
        text = extract_text(result.html)
        if text:
            extracted_text = text
            word_count = count_words(text)
            if content_hash:
                txt_path = pages_dir / f"{content_hash}.txt"
                if not txt_path.exists():
                    txt_path.write_text(text, encoding="utf-8", errors="replace")
                extracted_text_path = str(txt_path.relative_to(Path.cwd()) if txt_path.is_relative_to(Path.cwd()) else txt_path)

    # --- Insert CompanyPage row ---
    page = CompanyPage(
        company_id=company_id,
        discovery_hit_id=discovery_hit_id,
        url=norm_url,
        final_url=result.final_url if result.final_url != result.url else None,
        raw_html_path=raw_html_path,
        http_status_code=result.status_code,
        content_type=result.content_type,
        content_hash=content_hash,
        fetched_at=datetime.now(timezone.utc),
        page_type=page_type,
        extracted_text=extracted_text,
        extracted_text_path=extracted_text_path,
        word_count=word_count,
    )
    session.add(page)
    session.flush()
    log.debug(
        "page saved: company=%s url=%r type=%s words=%s",
        company_id,
        norm_url,
        page_type.value if page_type else None,
        word_count,
    )
    return page, True
