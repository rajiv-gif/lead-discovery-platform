from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import PageType
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company import Company
    from src.models.discovery_hit import DiscoveryHit


class CompanyPage(UUIDPrimaryKey, TimestampMixin, Base):
    """A scraped page belonging to a company.

    ``raw_html_path`` is a relative path to the HTML file on disk (under
    ``data/pages/``). Raw HTML is **never** stored in this table — only
    the path reference and fetch metadata.

    ``content_hash`` is the SHA-256 of the raw HTML, used to detect
    whether a page has changed between scrapes.

    ``extracted_text`` holds the boilerplate-stripped plain text extracted
    from the page (queryable in PostgreSQL). The same text is also written
    to ``extracted_text_path`` on disk as a ``.txt`` artifact.
    """

    __tablename__ = "company_pages"

    company_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    # Which discovery hit triggered this scrape (nullable for manually added pages)
    discovery_hit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("discovery_hits.id"),
        nullable=True,
        index=True,
    )
    # Normalised URL used as the dedup key (scheme+host lowercased, no trailing slash)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Final URL after all redirects (may differ from url)
    final_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Relative path, e.g. "data/pages/abc123.html" — content lives on disk only
    raw_html_path: Mapped[str] = mapped_column(Text, nullable=False)
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # HTTP Content-Type header value (e.g. "text/html; charset=utf-8")
    content_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # SHA-256 hex digest of the raw HTML for change detection
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Page classification ---
    page_type: Mapped[Optional[PageType]] = mapped_column(
        SAEnum(PageType, name="pagetype", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
        index=True,
    )

    # --- Extracted text ---
    # Boilerplate-stripped plain text; stored in DB for querying
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Relative path to the .txt artifact on disk (e.g. "data/pages/abc123.txt")
    extracted_text_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Word count of extracted_text (for quality filtering)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    company: Mapped[Company] = relationship("Company", back_populates="pages")
    discovery_hit: Mapped[Optional[DiscoveryHit]] = relationship(
        "DiscoveryHit", back_populates="pages"
    )
