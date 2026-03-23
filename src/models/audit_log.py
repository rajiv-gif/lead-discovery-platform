from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.models.enums import AuditAction
from src.models.mixins import UUIDPrimaryKey


class AuditLog(UUIDPrimaryKey, Base):
    """Immutable audit trail for all domain record changes.

    Uses a generic ``table_name`` + ``record_id`` reference instead of
    per-table FKs so a single table covers all entities.

    No ``updated_at`` — audit records are write-once.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        # Fast lookups by entity: "give me all changes to company X"
        Index("ix_audit_log_table_record", "table_name", "record_id"),
    )

    # Write-once timestamp; no updated_at
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Name of the SQLAlchemy __tablename__ being audited
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    # PK of the row that changed
    record_id: Mapped[uuid.UUID] = mapped_column(SAUUID(as_uuid=True), nullable=False)
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, name="auditaction", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    # Who or what made the change ("cli", "pipeline", a username, etc.)
    changed_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
