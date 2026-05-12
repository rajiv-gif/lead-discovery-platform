"""add_tiling_and_query_variants

Revision ID: 86f4acea0834
Revises: 688f1b33f9de
Create Date: 2026-05-12 12:39:03.531154
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '86f4acea0834'
down_revision: Union[str, None] = '688f1b33f9de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('geo_tile_size_km', sa.Float(), nullable=True))
    op.add_column('campaigns', sa.Column('places_query_variants', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('campaigns', 'places_query_variants')
    op.drop_column('campaigns', 'geo_tile_size_km')
