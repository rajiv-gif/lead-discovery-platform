from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.source import Source
    from src.models.extraction_run import ExtractionRun


class Lead(UUIDPrimaryKey, TimestampMixin, Base):
    """One extracted lead per source.

    Field values are populated by the extraction stage.
    ``verification_status`` and ``score`` are set by later stages.
    """

    __tablename__ = "lead"

    source_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("source.id"), nullable=False, index=True
    )

    # --- Extracted fields ---
    company_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # --- Pipeline status ---
    extraction_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )

    # --- Scoring ---
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_band: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # --- Review ---
    review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source: Mapped[Source] = relationship("Source", back_populates="lead")
    extraction_runs: Mapped[list[ExtractionRun]] = relationship(
        "ExtractionRun", back_populates="lead"
    )
