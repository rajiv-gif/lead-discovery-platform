from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company import Company
    from src.models.email import Email
    from src.models.phone import Phone


class Contact(UUIDPrimaryKey, TimestampMixin, Base):
    """An individual person at a company.

    A company can have multiple contacts. Each contact can have multiple
    emails and phones. For company-level generic contact info (info@, main
    switchboard) use ``Email.company_id`` / ``Phone.company_id`` directly.
    """

    __tablename__ = "contacts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    first_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Stored separately from first/last to handle single-field sources
    full_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Where we found this contact (e.g. "company_page", "linkedin")
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_fields: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    company: Mapped[Company] = relationship("Company", back_populates="contacts")
    emails: Mapped[list[Email]] = relationship("Email", back_populates="contact")
    phones: Mapped[list[Phone]] = relationship("Phone", back_populates="contact")
