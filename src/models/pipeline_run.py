"""ORM model for persisted pipeline stage run records."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UUID, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class PipelineRun(Base):
    """One record per pipeline stage execution for a campaign.

    Written by the task registry on start and on completion so the UI can
    display last-run timestamps and errors even after a server restart.
    The registry (in-memory) is the authoritative source while the server
    is running; this table is the persistent audit trail.
    """

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    # "running" | "done" | "failed" | "cancelled"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    elapsed_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
