from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Text, UniqueConstraint
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
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

    Indexing:
        - Compound index ``ix_company_leads_review_queue`` on
          (review_status, score DESC) is the primary access path for the
          review queue and is defined via raw SQL in the Alembic migration
          because SQLAlchemy __table_args__ cannot express DESC column
          ordering without raw text expressions.
        - ``ix_company_leads_status`` (leadstatus) is kept separately —
          it covers queries that filter by pipeline status (new, qualified,
          etc.) independent of review_status.
        - The former single-column ``ix_company_leads_review_status`` index
          is NOT created: the compound index left-prefix makes it redundant.
    """

    __tablename__ = "company_leads"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_company_lead_company"),
        # ix_company_leads_review_queue (review_status, score DESC) is
        # defined in the migration via op.execute(CREATE INDEX ... DESC).
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
        SAEnum(LeadStatus, name="leadstatus", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=LeadStatus.NEW,
        index=True,
    )

    # --- Scoring ---
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_band: Mapped[Optional[ScoreBand]] = mapped_column(
        SAEnum(ScoreBand, name="scoreband", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    # Per-dimension breakdown: {completeness, verification, source, extraction}
    # Enables score auditing and weight tuning without re-running the scorer.
    score_details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # --- Review ---
    review_status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(ReviewStatus, name="reviewstatus", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ReviewStatus.PENDING,
        # NOT indexed here — covered by compound (review_status, score DESC) in migration
    )
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Timestamp when review decision was made (approved OR rejected)
    review_decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Lifecycle timestamps ---
    qualified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    converted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Overflow for campaign-specific or integration metadata
    extra_fields: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    company: Mapped[Company] = relationship("Company", back_populates="lead")
    campaign: Mapped[Optional[Campaign]] = relationship(
        "Campaign", back_populates="company_leads"
    )
