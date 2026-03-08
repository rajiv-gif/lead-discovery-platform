from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import PhoneType
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company import Company
    from src.models.contact import Contact


class Phone(UUIDPrimaryKey, TimestampMixin, Base):
    """A phone number associated with a contact or company.

    ``number`` stores the normalised E.164 value after verification.
    ``raw_number`` preserves the original string as extracted.

    Ownership mirrors Email: one of ``contact_id`` or ``company_id``
    should be set; both nullable to allow either.
    """

    __tablename__ = "phones"

    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("contacts.id"),
        nullable=True,
        index=True,
    )
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
        index=True,
    )
    # E.164 format after normalisation (e.g. +14155552671)
    number: Mapped[str] = mapped_column(Text, nullable=False)
    # Raw string as extracted before normalisation
    raw_number: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone_type: Mapped[PhoneType] = mapped_column(
        SAEnum(PhoneType, name="phonetype"),
        nullable=False,
        default=PhoneType.UNKNOWN,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    contact: Mapped[Optional[Contact]] = relationship("Contact", back_populates="phones")
    company: Mapped[Optional[Company]] = relationship(
        "Company",
        back_populates="phones",
        foreign_keys=[company_id],
    )
