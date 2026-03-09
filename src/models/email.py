from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import EmailStatus
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company import Company
    from src.models.contact import Contact


class Email(UUIDPrimaryKey, TimestampMixin, Base):
    """An email address anchored to a company, optionally linked to a contact.

    ``company_id`` is REQUIRED on every row — all emails must belong to a
    company. ``contact_id`` is optional and links the address to a specific
    person at that company.

    Access patterns:
        - company-level generic address (info@acme.com):
              company_id set, contact_id NULL
        - contact-level personal address (john@acme.com):
              company_id set, contact_id set

    The CHECK constraint ``ck_email_has_owner`` is kept explicit even though
    ``company_id NOT NULL`` already prevents orphans, so the intent is clear
    to future readers.
    """

    __tablename__ = "emails"
    __table_args__ = (
        CheckConstraint(
            "contact_id IS NOT NULL OR company_id IS NOT NULL",
            name="ck_email_has_owner",
        ),
    )

    # Required: every email must trace back to a company
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
    address: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    status: Mapped[EmailStatus] = mapped_column(
        SAEnum(EmailStatus, name="emailstatus"),
        nullable=False,
        default=EmailStatus.UNVERIFIED,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # True/False after MX lookup; None = not yet checked
    mx_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    contact: Mapped[Optional[Contact]] = relationship("Contact", back_populates="emails")
    company: Mapped[Company] = relationship(
        "Company",
        back_populates="emails",
        foreign_keys=[company_id],
    )
