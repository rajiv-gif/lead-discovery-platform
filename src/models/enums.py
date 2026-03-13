"""Centralised enum definitions for all domain models.

All Python enums are str-enums so values serialise directly to/from JSON
and database strings without extra coercion. Each enum maps 1-to-1 to a
PostgreSQL native enum type created in the Alembic migration.

PostgreSQL type name convention: lowercase, no separator (e.g. CampaignStatus → campaignstatus).
"""
from __future__ import annotations

import enum


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class DiscoveryHitStatus(str, enum.Enum):
    PENDING = "pending"
    SCRAPED = "scraped"
    EXTRACTED = "extracted"
    FAILED = "failed"
    SKIPPED = "skipped"


class DiscoveryHitSourceType(str, enum.Enum):
    # Phase 1 source types only. LinkedIn adapter is Phase 2+ — do not add
    # LINKEDIN here until that work is scoped and the migration is ready.
    GOOGLE_MAPS = "google_maps"
    DIRECTORY = "directory"
    MANUAL = "manual"
    WEB_SEARCH = "web_search"


class GeoMethod(str, enum.Enum):
    """Geo-targeting method used when running discovery for a campaign.

    Maps 1-to-1 to the ``geomethod`` PostgreSQL enum type created in the
    ``b2c3d4e5f6a1`` migration.
    """

    CITY = "city"
    POSTAL_CODE = "postal_code"
    BOUNDING_BOX = "bounding_box"
    CENTER_RADIUS = "center_radius"


class EmailStatus(str, enum.Enum):
    UNVERIFIED = "unverified"
    VALID = "valid"
    INVALID = "invalid"
    CATCH_ALL = "catch_all"
    RISKY = "risky"


class PhoneType(str, enum.Enum):
    MOBILE = "mobile"
    OFFICE = "office"
    DIRECT = "direct"
    FAX = "fax"
    UNKNOWN = "unknown"


class LeadStatus(str, enum.Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    CONTACTED = "contacted"
    CONVERTED = "converted"
    CHURNED = "churned"


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_EDIT = "needs_edit"


class ScoreBand(str, enum.Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    DISQUALIFIED = "disqualified"


class AuditAction(str, enum.Enum):
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class SuppressionType(str, enum.Enum):
    EMAIL = "email"
    DOMAIN = "domain"
    COMPANY = "company"
    PHONE = "phone"


class SuppressionReason(str, enum.Enum):
    UNSUBSCRIBED = "unsubscribed"
    BOUNCED = "bounced"
    SPAM_COMPLAINT = "spam_complaint"
    DO_NOT_CONTACT = "do_not_contact"
    COMPETITOR = "competitor"
    MANUAL = "manual"


class PageType(str, enum.Enum):
    """Classification of a scraped company page.

    Maps 1-to-1 to the ``pagetype`` PostgreSQL enum type.
    Priority order for supplemental page selection: ABOUT → CONTACT → TEAM,
    then SERVICES/OTHER as fallbacks if a slot is still unfilled.
    """

    HOMEPAGE = "homepage"
    ABOUT = "about"
    CONTACT = "contact"
    TEAM = "team"
    SERVICES = "services"
    OTHER = "other"
