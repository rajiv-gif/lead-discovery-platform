from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
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

    All ``Email`` and ``Phone`` rows require ``company_id`` — so
    ``company.emails`` and ``company.phones`` return ALL addresses for this
    company (both generic/direct and contact-linked). Filter by
    ``contact_id IS NULL`` in application code for generic-only entries.
    """

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # True when the business has a website (set from Places API website_uri field).
    # False when website_uri is absent — used by WEB_AGENCY campaigns to fast-path
    # these businesses through the pipeline (no scrape, no LLM extraction needed).
    has_website: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # domain is extracted from website for dedup and suppression lookups
    domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    # Stable Google Places place_id — primary dedup key for Places-sourced companies.
    # Stored as a dedicated indexed column (not inside extra_fields) so lookups are
    # fast (B-tree index) without needing a GIN index on the JSONB blob.
    # Null for companies created by other means (manual entry, directory scraping, etc.)
    google_place_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
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
    extra_fields: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    pages: Mapped[list[CompanyPage]] = relationship("CompanyPage", back_populates="company")
    contacts: Mapped[list[Contact]] = relationship("Contact", back_populates="company")
    # 1:1 — a company has at most one lead record
    lead: Mapped[Optional[CompanyLead]] = relationship(
        "CompanyLead", back_populates="company", uselist=False
    )
    discovery_hits: Mapped[list[DiscoveryHit]] = relationship(
        "DiscoveryHit", back_populates="company"
    )
    # All emails where company_id matches — direct and contact-linked combined.
    # Previous viewonly/filtered relationship removed: company_id is now required
    # on ALL Email rows, so no filtering by contact_id is needed here.
    emails: Mapped[list[Email]] = relationship(
        "Email",
        back_populates="company",
        foreign_keys="[Email.company_id]",
    )
    # All phones where company_id matches — direct and contact-linked combined.
    phones: Mapped[list[Phone]] = relationship(
        "Phone",
        back_populates="company",
        foreign_keys="[Phone.company_id]",
    )
