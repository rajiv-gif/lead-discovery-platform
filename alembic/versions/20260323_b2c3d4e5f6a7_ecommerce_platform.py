"""Add ecommerce_platform column to campaigns.

Revision ID: b2c3d4e5f6a7
Revises: 20260323_phase8
Create Date: 2026-03-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "20260323_phase8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("ecommerce_platform", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "ecommerce_platform")
