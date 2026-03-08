from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import EmailStatus
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company import Company
    from src.models.contact import Contact


class Email(UUIDPrimaryKey, TimestampMixin, Base):
    """An email address associated with a contact or company.

    Exactly one of ``contact_id`` or ``company_id`` should be set:
    - ``contact_id`` — personal address (e.g. john@acme.com)
    - ``company_id`` only — generic company address (e.g. info@acme.com)

    This is enforced at the application layer, not via a DB constraint,
    to keep migrations simple.
    """

    __tablename__ = "emails"

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
    company: Mapped[Optional[Company]] = relationship(
        "Company",
        back_populates="emails",
        foreign_keys=[company_id],
    )
