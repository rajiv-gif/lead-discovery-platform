"""add_search_geo_scope

Revision ID: 688f1b33f9de
Revises: 5a8684f5817f
Create Date: 2026-05-11 14:19:37.970489
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '688f1b33f9de'
down_revision: Union[str, None] = '5a8684f5817f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('search_geo_scope', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('campaigns', 'search_geo_scope')
