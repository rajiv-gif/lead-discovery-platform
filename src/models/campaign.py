from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SAEnum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import CampaignStatus
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company_lead import CompanyLead
    from src.models.discovery_hit import DiscoveryHit


class Campaign(UUIDPrimaryKey, TimestampMixin, Base):
    """A lead discovery campaign.

    Groups discovery hits and company leads under a named initiative.
    """

    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        SAEnum(CampaignStatus, name="campaignstatus"),
        nullable=False,
        default=CampaignStatus.DRAFT,
        index=True,
    )

    discovery_hits: Mapped[list[DiscoveryHit]] = relationship(
        "DiscoveryHit", back_populates="campaign"
    )
    company_leads: Mapped[list[CompanyLead]] = relationship(
        "CompanyLead", back_populates="campaign"
    )
