from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, Text, UniqueConstraint
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

    Tracks discovery and extraction pipeline state only. Scraping
    metadata (fetched_at, http_status_code, raw HTML path) belongs on
    ``CompanyPage``, which is created after a successful scrape.

    ``company_id`` is null until extraction resolves the hit to a company.
    ``error_message`` records the failure reason when status=failed,
    allowing pipeline debugging without re-running the full stage.
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
    # Populated when status = failed; null otherwise
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="discovery_hits")
    company: Mapped[Optional[Company]] = relationship(
        "Company", back_populates="discovery_hits"
    )
    pages: Mapped[list[CompanyPage]] = relationship(
        "CompanyPage", back_populates="discovery_hit"
    )
