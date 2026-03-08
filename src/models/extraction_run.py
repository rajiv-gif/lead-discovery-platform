from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.source import Source
    from src.models.lead import Lead


class ExtractionRun(UUIDPrimaryKey, TimestampMixin, Base):
    """Metadata for a single LLM extraction call.

    Prompt and response content live on disk at ``prompt_path``
    and ``response_path`` respectively.
    """

    __tablename__ = "extraction_run"

    source_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("source.id"), nullable=False, index=True
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("lead.id"), nullable=True
    )

    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    source: Mapped[Source] = relationship("Source", back_populates="extraction_runs")
    lead: Mapped[Optional[Lead]] = relationship("Lead", back_populates="extraction_runs")
