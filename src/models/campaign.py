from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SAEnum, Float, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.enums import CampaignGoal, CampaignStatus, DiscoverySource, GeoMethod
from src.models.mixins import TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from src.models.company_lead import CompanyLead
    from src.models.discovery_hit import DiscoveryHit


class Campaign(UUIDPrimaryKey, TimestampMixin, Base):
    """A lead discovery campaign.

    Groups discovery hits and company leads under a named initiative.

    Geo targeting is configured at campaign creation time via ``geo_method``
    and the corresponding coordinate columns. Only the fields relevant to the
    chosen method need to be populated:

    - ``CITY``          → ``geo_city``, ``geo_country``
    - ``POSTAL_CODE``   → ``geo_postal_code``
    - ``BOUNDING_BOX``  → ``geo_sw_lat/lng``, ``geo_ne_lat/lng``
    - ``CENTER_RADIUS`` → ``geo_center_lat/lng``, ``geo_radius_m``
    - ``STATE``         → ``geo_state``, ``geo_country``, ``geo_cities_selected``

    For ``WEB_SEARCH`` campaigns, geo fields are unused; ``search_queries``
    holds the list of search strings to run against DuckDuckGo.

    Validation of required fields is enforced at the CLI layer, not by DB
    constraints, to keep the migration simple and avoid cross-column CHECKs.
    """

    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        SAEnum(CampaignStatus, name="campaignstatus", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CampaignStatus.DRAFT,
        index=True,
    )

    # --- Campaign goal ---
    # LEAD_GEN (default) — current behaviour, unchanged.
    # WEB_AGENCY — surface businesses with no/outdated website; gated by WEB_AGENCY_ENABLED.
    campaign_goal: Mapped[CampaignGoal] = mapped_column(
        SAEnum(CampaignGoal, name="campaigngoal", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CampaignGoal.LEAD_GEN,
        server_default="lead_gen",
    )

    # --- Discovery source ---
    discovery_source: Mapped[DiscoverySource] = mapped_column(
        SAEnum(DiscoverySource, name="discoverysource", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DiscoverySource.GOOGLE_PLACES,
    )

    # --- Discovery configuration ---
    # geo_method is required for GOOGLE_PLACES campaigns; nullable for WEB_SEARCH.
    geo_method: Mapped[Optional[GeoMethod]] = mapped_column(
        SAEnum(GeoMethod, name="geomethod", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    # Business type / niche used as the Places textQuery (e.g. "dentists").
    # Defaults to "dentists" in Python; migration renames column from specialty.
    niche: Mapped[str] = mapped_column(Text, nullable=False, default="dentists")

    # --- City / postal-code fields ---
    geo_city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    geo_postal_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    geo_country: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- State / multi-city fields ---
    geo_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSONB list of city strings selected by the user, e.g. ["New York", "Buffalo"]
    geo_cities_selected: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # --- Bounding-box fields (south-west and north-east corners) ---
    geo_sw_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_sw_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_ne_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_ne_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- Center + radius fields ---
    geo_center_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_center_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_radius_m: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- Web-search campaign fields (WEB_SEARCH discovery_source only) ---
    # JSONB list of search query strings, e.g. ["luxury fashion online", "DTC fashion brand"]
    search_queries: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # --- Ecommerce platform filter (WEB_SEARCH only) ---
    # "shopify" → auto-prepend site:myshopify.com and run Shopify verification
    # "woocommerce" → future; "any" / None → no platform filter
    ecommerce_platform: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    discovery_hits: Mapped[list[DiscoveryHit]] = relationship(
        "DiscoveryHit", back_populates="campaign"
    )
    company_leads: Mapped[list[CompanyLead]] = relationship(
        "CompanyLead", back_populates="campaign"
    )
