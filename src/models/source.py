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
    from src.models.run import Run
    from src.models.lead import Lead
    from src.models.extraction_run import ExtractionRun


class Source(UUIDPrimaryKey, TimestampMixin, Base):
    """A URL to be or already scraped.

    ``page_path`` stores a relative path to the HTML file on disk.
    HTML content is never stored in the database.
    """

    __tablename__ = "source"

    run_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    page_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship("Run", back_populates="sources")
    lead: Mapped[Optional[Lead]] = relationship("Lead", back_populates="source", uselist=False)
    extraction_runs: Mapped[list[ExtractionRun]] = relationship(
        "ExtractionRun", back_populates="source"
    )
