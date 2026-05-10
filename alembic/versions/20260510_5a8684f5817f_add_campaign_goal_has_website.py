"""add_campaign_goal_has_website

Revision ID: 5a8684f5817f
Revises: b2c3d4e5f6a7
Create Date: 2026-05-10 18:19:33.316970
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a8684f5817f'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    campaigngoal = sa.Enum('lead_gen', 'web_agency', name='campaigngoal')
    campaigngoal.create(op.get_bind(), checkfirst=True)
    op.add_column('campaigns', sa.Column('campaign_goal', sa.Enum('lead_gen', 'web_agency', name='campaigngoal'), server_default='lead_gen', nullable=False))
    op.add_column('companies', sa.Column('has_website', sa.Boolean(), server_default='true', nullable=False))


def downgrade() -> None:
    op.drop_column('companies', 'has_website')
    op.drop_column('campaigns', 'campaign_goal')
    op.execute("DROP TYPE IF EXISTS campaigngoal")
