from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import DiscoveryHitSourceType, DiscoveryHitStatus
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.campaign import Campaign
    from src.models.company import Company
    from src.models.company_page import CompanyPage


class DiscoveryHit(UUIDPrimaryKey, TimestampMixin, Base):
    """A single URL found during discovery for a campaign.

    ``company_id`` is null until extraction resolves the hit to a company.
    ``raw_html_path`` is never stored here — see CompanyPage for scraped content.
    """

    __tablename__ = "discovery_hits"
    __table_args__ = (
        # Prevent the same URL being added twice to the same campaign
        UniqueConstraint("campaign_id", "source_url", name="uq_discovery_hit_campaign_url"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("campaigns.id"),
        nullable=False,
        index=True,
    )
    # Set after extraction resolves the hit to a known company
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
        index=True,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[DiscoveryHitSourceType] = mapped_column(
        SAEnum(DiscoveryHitSourceType, name="discoveryhitsourcetype"),
        nullable=False,
        default=DiscoveryHitSourceType.MANUAL,
    )
    status: Mapped[DiscoveryHitStatus] = mapped_column(
        SAEnum(DiscoveryHitStatus, name="discoveryhitstatus"),
        nullable=False,
        default=DiscoveryHitStatus.PENDING,
        index=True,
    )
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="discovery_hits")
    company: Mapped[Optional[Company]] = relationship(
        "Company", back_populates="discovery_hits"
    )
    pages: Mapped[list[CompanyPage]] = relationship(
        "CompanyPage", back_populates="discovery_hit"
    )
