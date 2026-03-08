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

    ``type`` + ``value`` is unique — you can't suppress the same email twice.
    ``expires_at`` is null for permanent suppression.

    Examples:
        type=EMAIL,  value="bad@example.com"   → block this address
        type=DOMAIN, value="competitor.com"    → block entire domain
        type=PHONE,  value="+14155550000"      → block this number
        type=COMPANY, value="Acme Corp"        → block by company name
    """

    __tablename__ = "suppression_list"
    __table_args__ = (
        UniqueConstraint("type", "value", name="uq_suppression_type_value"),
    )

    type: Mapped[SuppressionType] = mapped_column(
        SAEnum(SuppressionType, name="suppressiontype"),
        nullable=False,
        index=True,
    )
    # The suppressed value (email address, domain, phone in E.164, company name)
    value: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    reason: Mapped[SuppressionReason] = mapped_column(
        SAEnum(SuppressionReason, name="suppressionreason"),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # None = permanent; set a future datetime for temporary suppression
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
