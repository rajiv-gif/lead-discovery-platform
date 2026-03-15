"""Phase 7 — add pipeline_runs table for persisted stage execution history.

Adds:
  - ``pipeline_runs`` table with columns:
      id, campaign_id, stage, status, started_at, finished_at,
      elapsed_seconds, error
  - Index on ``campaign_id`` for fast per-campaign queries

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-03-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a1b2c3d4"
down_revision: Union[str, None] = "d4e5f6a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("campaign_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_pipeline_runs_campaign_id",
        "pipeline_runs",
        ["campaign_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_campaign_id", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
