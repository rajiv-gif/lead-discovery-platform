from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company_lead import CompanyLead
    from src.models.company_page import CompanyPage
    from src.models.contact import Contact
    from src.models.discovery_hit import DiscoveryHit
    from src.models.email import Email
    from src.models.phone import Phone


class Company(UUIDPrimaryKey, TimestampMixin, Base):
    """A company record.

    The central entity of the platform. Created during extraction and
    enriched by subsequent pipeline stages.
    """

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # domain is extracted from website for dedup and suppression lookups
    domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    industry: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    employee_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    founded_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Overflow for source-specific fields that don't map to core columns
    extra_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    pages: Mapped[list[CompanyPage]] = relationship("CompanyPage", back_populates="company")
    contacts: Mapped[list[Contact]] = relationship("Contact", back_populates="company")
    # 1:1 — a company has at most one lead record
    lead: Mapped[Optional[CompanyLead]] = relationship(
        "CompanyLead", back_populates="company", uselist=False
    )
    discovery_hits: Mapped[list[DiscoveryHit]] = relationship(
        "DiscoveryHit", back_populates="company"
    )
    # Company-level emails (e.g. info@company.com, not tied to a contact)
    emails: Mapped[list[Email]] = relationship(
        "Email",
        primaryjoin="and_(Email.company_id == Company.id, Email.contact_id == None)",
        back_populates="company",
        viewonly=True,
    )
    # Company-level phones (e.g. main office number)
    phones: Mapped[list[Phone]] = relationship(
        "Phone",
        primaryjoin="and_(Phone.company_id == Company.id, Phone.contact_id == None)",
        back_populates="company",
        viewonly=True,
    )
