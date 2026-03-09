from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import PhoneType
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company import Company
    from src.models.contact import Contact


class Phone(UUIDPrimaryKey, TimestampMixin, Base):
    """A phone number anchored to a company, optionally linked to a contact.

    ``company_id`` is REQUIRED on every row — all phone numbers must belong
    to a company. ``contact_id`` is optional and links the number to a
    specific person at that company.

    ``number`` stores the normalised E.164 value after verification.
    ``raw_number`` preserves the original string as extracted.

    Access patterns:
        - company main line (switchboard):
              company_id set, contact_id NULL
        - direct dial / mobile:
              company_id set, contact_id set

    The CHECK constraint ``ck_phone_has_owner`` mirrors the intent on Email:
    redundant given ``company_id NOT NULL``, but kept for clarity.
    """

    __tablename__ = "phones"
    __table_args__ = (
        CheckConstraint(
            "contact_id IS NOT NULL OR company_id IS NOT NULL",
            name="ck_phone_has_owner",
        ),
    )

    # Required: every phone must trace back to a company
    company_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    # Optional: links to a specific person at the company
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("contacts.id"),
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
    company: Mapped[Company] = relationship(
        "Company",
        back_populates="phones",
        foreign_keys=[company_id],
    )
