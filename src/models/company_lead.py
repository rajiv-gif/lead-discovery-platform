from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, JSON, Text, UniqueConstraint
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import LeadStatus, ReviewStatus, ScoreBand
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.campaign import Campaign
    from src.models.company import Company


class CompanyLead(UUIDPrimaryKey, TimestampMixin, Base):
    """Lead record derived from a company.

    This is a real application table (not a view). It tracks the full
    lead lifecycle for a company: scoring, review, and CRM status.

    The unique constraint on ``company_id`` enforces the 1:1 relationship
    with Company — a company can only be a lead once.
    """

    __tablename__ = "company_leads"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_company_lead_company"),
    )

    # 1:1 with Company; enforced by unique constraint above
    company_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    # Which campaign generated this lead (nullable for manually created leads)
    campaign_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("campaigns.id"),
        nullable=True,
        index=True,
    )
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus, name="leadstatus"),
        nullable=False,
        default=LeadStatus.NEW,
        index=True,
    )
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_band: Mapped[Optional[ScoreBand]] = mapped_column(
        SAEnum(ScoreBand, name="scoreband"),
        nullable=True,
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(ReviewStatus, name="reviewstatus"),
        nullable=False,
        default=ReviewStatus.PENDING,
        index=True,
    )
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Lifecycle timestamps — set by application when status transitions occur
    qualified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    converted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extra_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    company: Mapped[Company] = relationship("Company", back_populates="lead")
    campaign: Mapped[Optional[Campaign]] = relationship(
        "Campaign", back_populates="company_leads"
    )
