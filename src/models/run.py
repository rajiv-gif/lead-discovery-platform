from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.source import Source


class Run(UUIDPrimaryKey, TimestampMixin, Base):
    """A single pipeline execution."""

    __tablename__ = "run"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    # {stage: {attempted: int, succeeded: int, failed: int}}
    stage_counts: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    sources: Mapped[list[Source]] = relationship("Source", back_populates="run")
