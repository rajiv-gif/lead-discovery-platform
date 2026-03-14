"""Phase 4.1 — add normalized_name_key to contacts for cross-run dedup.

Adds:
  - ``contacts.normalized_name_key``   (nullable TEXT, indexed)
  - Backfills all existing rows using normalize_name_key() from Python
  - Partial unique index ``(company_id, normalized_name_key) WHERE normalized_name_key IS NOT NULL``
  - Regular index ``ix_contacts_normalized_name_key`` on ``normalized_name_key``

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-03-14
"""
from __future__ import annotations

import sys
import os
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# Ensure src/ is on the path so we can import normalize_name_key
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from extraction.models import normalize_name_key  # noqa: E402

revision: str = "d4e5f6a1b2c3"
down_revision: Union[str, None] = "c3d4e5f6a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # 1. Add the nullable column
    op.add_column(
        "contacts",
        sa.Column("normalized_name_key", sa.Text(), nullable=True),
    )

    # 2. Backfill using Python-level normalize_name_key()
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT id, full_name FROM contacts WHERE full_name IS NOT NULL")
    )
    for row in result:
        key = normalize_name_key(row.full_name)
        conn.execute(
            sa.text(
                "UPDATE contacts SET normalized_name_key = :key WHERE id = :id"
            ),
            {"key": key, "id": row.id},
        )

    # 3. Partial unique index: (company_id, normalized_name_key) WHERE NOT NULL
    #    Prevents duplicate contacts for the same normalised name within a company
    #    across runs, while allowing multiple NULL-key rows (edge case: contacts
    #    with NULL full_name).
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX ix_contacts_company_normalized_name "
            "ON contacts (company_id, normalized_name_key) "
            "WHERE normalized_name_key IS NOT NULL"
        )
    )

    # 4. Regular index for fast lookups by normalized key alone
    op.create_index(
        "ix_contacts_normalized_name_key",
        "contacts",
        ["normalized_name_key"],
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index("ix_contacts_normalized_name_key", table_name="contacts")
    op.execute(
        sa.text("DROP INDEX IF EXISTS ix_contacts_company_normalized_name")
    )
    op.drop_column("contacts", "normalized_name_key")
