from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.models.enums import SuppressionReason, SuppressionType
from src.models.mixins import TimestampMixin, UUIDPrimaryKey


class SuppressionList(UUIDPrimaryKey, TimestampMixin, Base):
    """Suppression entries that block outreach to specific values.

    ``suppression_type`` + ``value`` is unique — you can't suppress the
    same email twice. ``expires_at`` is null for permanent suppression.

    Column is named ``suppression_type`` (not ``type``) to avoid shadowing
    the Python built-in and SQLAlchemy's internal polymorphic type column.

    Examples:
        suppression_type=EMAIL,  value="bad@example.com"   → block this address
        suppression_type=DOMAIN, value="competitor.com"    → block entire domain
        suppression_type=PHONE,  value="+14155550000"      → block this number
        suppression_type=COMPANY, value="Acme Corp"        → block by company name
    """

    __tablename__ = "suppression_list"
    __table_args__ = (
        UniqueConstraint("suppression_type", "value", name="uq_suppression_type_value"),
    )

    suppression_type: Mapped[SuppressionType] = mapped_column(
        SAEnum(SuppressionType, name="suppressiontype", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    value: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    reason: Mapped[SuppressionReason] = mapped_column(
        SAEnum(SuppressionReason, name="suppressionreason", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # None = permanent; set a future datetime for temporary suppression
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
