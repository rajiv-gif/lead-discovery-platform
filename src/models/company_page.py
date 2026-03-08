from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
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
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Relative path, e.g. "data/pages/abc123.html" — content lives on disk only
    raw_html_path: Mapped[str] = mapped_column(Text, nullable=False)
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # SHA-256 hex digest of the raw HTML for change detection
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    company: Mapped[Company] = relationship("Company", back_populates="pages")
    discovery_hit: Mapped[Optional[DiscoveryHit]] = relationship(
        "DiscoveryHit", back_populates="pages"
    )
