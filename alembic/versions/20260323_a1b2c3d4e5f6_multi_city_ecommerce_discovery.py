"""Phase 8 — multi-city state campaigns + ecommerce web-search discovery.

Adds:
  - GeoMethod.STATE enum value (alters geomethod PostgreSQL enum)
  - geo_state, geo_cities_selected columns on campaigns
  - DiscoverySource enum (new discoverysource PostgreSQL enum)
  - discovery_source, search_queries columns on campaigns
  - geo_method made nullable (WEB_SEARCH campaigns have no geo)

Revision ID: a1b2c3d4e5f6
Revises: f6a1b2c3d4e5
Create Date: 2026-03-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260323_phase8"
down_revision = "f6a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add STATE to the geomethod enum
    op.execute("ALTER TYPE geomethod ADD VALUE IF NOT EXISTS 'state'")

    # 2. Create discoverysource enum and add discovery_source column
    discoverysource = postgresql.ENUM(
        "google_places", "web_search",
        name="discoverysource",
        create_type=False,
    )
    discoverysource.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "campaigns",
        sa.Column(
            "discovery_source",
            sa.Enum("google_places", "web_search", name="discoverysource"),
            nullable=False,
            server_default="google_places",
        ),
    )

    # 3. Add geo_state and geo_cities_selected
    op.add_column("campaigns", sa.Column("geo_state", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("geo_cities_selected", postgresql.JSONB(), nullable=True))

    # 4. Add search_queries
    op.add_column("campaigns", sa.Column("search_queries", postgresql.JSONB(), nullable=True))

    # 5. Make geo_method nullable (WEB_SEARCH campaigns don't need it)
    op.alter_column("campaigns", "geo_method", nullable=True)

    # 6. Remove server_default from discovery_source now that existing rows have it
    op.alter_column("campaigns", "discovery_source", server_default=None)


def downgrade() -> None:
    # Reverse column additions
    op.drop_column("campaigns", "search_queries")
    op.drop_column("campaigns", "geo_cities_selected")
    op.drop_column("campaigns", "geo_state")
    op.drop_column("campaigns", "discovery_source")

    # Make geo_method non-nullable again
    op.alter_column("campaigns", "geo_method", nullable=False)

    # Drop discoverysource enum
    op.execute("DROP TYPE IF EXISTS discoverysource")

    # Note: Cannot remove enum values from PostgreSQL geomethod enum in downgrade.
    # The 'state' value will remain but unused.
