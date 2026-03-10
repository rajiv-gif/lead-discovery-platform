"""Add discovery geo fields and google_place_id.

Adds:
  - ``geomethod`` PostgreSQL enum type
  - ``campaigns.geo_method`` (NOT NULL, backfilled 'city')
  - ``campaigns.specialty`` (NOT NULL, backfilled 'dentists')
  - ``campaigns.geo_city/postal_code/country`` (nullable text)
  - ``campaigns.geo_sw_lat/lng``, ``geo_ne_lat/lng`` (nullable float, bounding box)
  - ``campaigns.geo_center_lat/lng``, ``geo_radius_m`` (nullable float/int)
  - ``companies.google_place_id`` (nullable text, indexed — primary dedup key for Places)
  - ``discovery_hits.discovery_query/method`` (nullable text)
  - ``discovery_hits.discovery_lat/lng`` (nullable float)
  - ``discovery_hits.discovery_radius_m``, ``api_response_rank`` (nullable int)
  - ``discovery_hits.discovered_at`` (nullable timestamptz)

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-03-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create the geomethod enum type
    conn.execute(
        sa.text(
            "CREATE TYPE geomethod AS ENUM "
            "('city', 'postal_code', 'bounding_box', 'center_radius')"
        )
    )

    # 2. campaigns — add geo_method (NOT NULL needs two-step: add nullable → backfill → set NOT NULL)
    op.add_column(
        "campaigns",
        sa.Column(
            "geo_method",
            sa.Enum("city", "postal_code", "bounding_box", "center_radius",
                    name="geomethod", create_type=False),
            nullable=True,
        ),
    )
    conn.execute(sa.text("UPDATE campaigns SET geo_method = 'city' WHERE geo_method IS NULL"))
    op.alter_column("campaigns", "geo_method", nullable=False)

    # 3. campaigns — specialty (NOT NULL, backfill 'dentists')
    op.add_column("campaigns", sa.Column("specialty", sa.Text(), nullable=True))
    conn.execute(sa.text("UPDATE campaigns SET specialty = 'dentists' WHERE specialty IS NULL"))
    op.alter_column("campaigns", "specialty", nullable=False)

    # 4. campaigns — nullable geo fields (city/postal_code/bounding_box/center_radius)
    op.add_column("campaigns", sa.Column("geo_city", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_postal_code", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_country", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_sw_lat", sa.Float(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_sw_lng", sa.Float(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_ne_lat", sa.Float(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_ne_lng", sa.Float(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_center_lat", sa.Float(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_center_lng", sa.Float(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_radius_m", sa.Integer(), nullable=True))

    # 5. companies — google_place_id (indexed for fast B-tree dedup lookups)
    op.add_column("companies", sa.Column("google_place_id", sa.Text(), nullable=True))
    op.create_index("ix_companies_google_place_id", "companies", ["google_place_id"])

    # 6. discovery_hits — provenance columns (all nullable; no backfill needed)
    op.add_column("discovery_hits", sa.Column("discovery_query", sa.Text(), nullable=True))
    op.add_column("discovery_hits", sa.Column("discovery_method", sa.Text(), nullable=True))
    op.add_column("discovery_hits", sa.Column("discovery_lat", sa.Float(), nullable=True))
    op.add_column("discovery_hits", sa.Column("discovery_lng", sa.Float(), nullable=True))
    op.add_column("discovery_hits", sa.Column("discovery_radius_m", sa.Integer(), nullable=True))
    op.add_column("discovery_hits", sa.Column("api_response_rank", sa.Integer(), nullable=True))
    op.add_column(
        "discovery_hits",
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse order: discovery_hits → companies → campaigns → enum type

    # discovery_hits
    op.drop_column("discovery_hits", "discovered_at")
    op.drop_column("discovery_hits", "api_response_rank")
    op.drop_column("discovery_hits", "discovery_radius_m")
    op.drop_column("discovery_hits", "discovery_lng")
    op.drop_column("discovery_hits", "discovery_lat")
    op.drop_column("discovery_hits", "discovery_method")
    op.drop_column("discovery_hits", "discovery_query")

    # companies
    op.drop_index("ix_companies_google_place_id", table_name="companies")
    op.drop_column("companies", "google_place_id")

    # campaigns — nullable geo fields
    op.drop_column("campaigns", "geo_radius_m")
    op.drop_column("campaigns", "geo_center_lng")
    op.drop_column("campaigns", "geo_center_lat")
    op.drop_column("campaigns", "geo_ne_lng")
    op.drop_column("campaigns", "geo_ne_lat")
    op.drop_column("campaigns", "geo_sw_lng")
    op.drop_column("campaigns", "geo_sw_lat")
    op.drop_column("campaigns", "geo_country")
    op.drop_column("campaigns", "geo_postal_code")
    op.drop_column("campaigns", "geo_city")

    # campaigns — NOT NULL columns
    op.drop_column("campaigns", "specialty")
    op.drop_column("campaigns", "geo_method")

    # enum type
    conn.execute(sa.text("DROP TYPE IF EXISTS geomethod"))
