"""Phase 2 scraper schema: pagetype enum and company_pages new columns.

Adds:
  - ``pagetype`` PostgreSQL enum type (homepage, about, contact, team, services, other)
  - ``company_pages.page_type``             (nullable pagetype enum, indexed)
  - ``company_pages.final_url``             (nullable text — URL after redirects)
  - ``company_pages.content_type``          (nullable text — HTTP Content-Type header)
  - ``company_pages.extracted_text``        (nullable text — boilerplate-stripped plain text)
  - ``company_pages.extracted_text_path``   (nullable text — path to .txt artifact on disk)
  - ``company_pages.word_count``            (nullable integer — word count of extracted text)
  - Index on ``company_pages(company_id, page_type)`` for efficient per-company page queries

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-03-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a1b2"
down_revision: Union[str, None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create the pagetype enum type
    conn.execute(sa.text(
        "DO $$ BEGIN CREATE TYPE pagetype AS ENUM "
        "('homepage', 'about', 'contact', 'team', 'services', 'other'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    ))

    # 2. company_pages — add page_type (nullable enum, indexed)
    op.add_column(
        "company_pages",
        sa.Column(
            "page_type",
            sa.Enum(
                "homepage", "about", "contact", "team", "services", "other",
                name="pagetype",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_company_pages_page_type", "company_pages", ["page_type"])

    # 3. company_pages — final_url (URL after all HTTP redirects)
    op.add_column("company_pages", sa.Column("final_url", sa.Text(), nullable=True))

    # 4. company_pages — content_type (HTTP Content-Type header value)
    op.add_column("company_pages", sa.Column("content_type", sa.Text(), nullable=True))

    # 5. company_pages — extracted_text (boilerplate-stripped plain text, stored in DB)
    op.add_column("company_pages", sa.Column("extracted_text", sa.Text(), nullable=True))

    # 6. company_pages — extracted_text_path (relative path to .txt file on disk)
    op.add_column("company_pages", sa.Column("extracted_text_path", sa.Text(), nullable=True))

    # 7. company_pages — word_count (word count of extracted_text for quality filtering)
    op.add_column("company_pages", sa.Column("word_count", sa.Integer(), nullable=True))


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse order
    op.drop_column("company_pages", "word_count")
    op.drop_column("company_pages", "extracted_text_path")
    op.drop_column("company_pages", "extracted_text")
    op.drop_column("company_pages", "content_type")
    op.drop_column("company_pages", "final_url")
    op.drop_index("ix_company_pages_page_type", table_name="company_pages")
    op.drop_column("company_pages", "page_type")

    conn.execute(sa.text("DROP TYPE IF EXISTS pagetype"))
