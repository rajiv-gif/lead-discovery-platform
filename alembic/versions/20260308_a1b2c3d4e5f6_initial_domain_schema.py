"""Initial domain schema.

Creates all 10 domain tables and their 11 PostgreSQL enum types.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Helpers — enum type creation / deletion
# ---------------------------------------------------------------------------

_ENUM_TYPES: list[tuple[str, list[str]]] = [
    ("campaignstatus", ["draft", "active", "paused", "completed", "archived"]),
    ("discoveryhitstatus", ["pending", "scraped", "extracted", "failed", "skipped"]),
    (
        "discoveryhitsourcetype",
        ["google_maps", "directory", "manual", "linkedin", "web_search"],
    ),
    ("emailstatus", ["unverified", "valid", "invalid", "catch_all", "risky"]),
    ("phonetype", ["mobile", "office", "direct", "fax", "unknown"]),
    (
        "leadstatus",
        ["new", "qualified", "disqualified", "contacted", "converted", "churned"],
    ),
    ("reviewstatus", ["pending", "approved", "rejected", "needs_edit"]),
    ("scoreband", ["hot", "warm", "cold", "disqualified"]),
    ("auditaction", ["INSERT", "UPDATE", "DELETE"]),
    ("suppressiontype", ["email", "domain", "company", "phone"]),
    (
        "suppressionreason",
        [
            "unsubscribed",
            "bounced",
            "spam_complaint",
            "do_not_contact",
            "competitor",
            "manual",
        ],
    ),
]


def _sa_enum(name: str) -> sa.Enum:
    """Return an SA Enum referencing an already-created PG type."""
    values = next(v for n, v in _ENUM_TYPES if n == name)
    return sa.Enum(*values, name=name, create_type=False)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create all PostgreSQL enum types first
    for type_name, values in _ENUM_TYPES:
        quoted = ", ".join(f"'{v}'" for v in values)
        conn.execute(
            sa.text(f"CREATE TYPE {type_name} AS ENUM ({quoted})")
        )

    # 2. campaigns (no FKs)
    op.create_table(
        "campaigns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", _sa_enum("campaignstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])

    # 3. companies (no FKs)
    op.create_table(
        "companies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("founded_year", sa.Integer(), nullable=True),
        sa.Column("extra_fields", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_companies_domain", "companies", ["domain"])

    # 4. suppression_list (no FKs)
    op.create_table(
        "suppression_list",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("type", _sa_enum("suppressiontype"), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("reason", _sa_enum("suppressionreason"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("type", "value", name="uq_suppression_type_value"),
    )
    op.create_index("ix_suppression_list_type", "suppression_list", ["type"])
    op.create_index("ix_suppression_list_value", "suppression_list", ["value"])

    # 5. audit_log (no FK — generic table_name + record_id)
    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("record_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", _sa_enum("auditaction"), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=True),
        sa.Column("old_values", JSONB(), nullable=True),
        sa.Column("new_values", JSONB(), nullable=True),
    )
    op.create_index(
        "ix_audit_log_table_record", "audit_log", ["table_name", "record_id"]
    )

    # 6. discovery_hits → campaigns, companies
    op.create_table(
        "discovery_hits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=True,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "source_type", _sa_enum("discoveryhitsourcetype"), nullable=False
        ),
        sa.Column(
            "status", _sa_enum("discoveryhitstatus"), nullable=False
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "campaign_id", "source_url", name="uq_discovery_hit_campaign_url"
        ),
    )
    op.create_index(
        "ix_discovery_hits_campaign_id", "discovery_hits", ["campaign_id"]
    )
    op.create_index(
        "ix_discovery_hits_company_id", "discovery_hits", ["company_id"]
    )
    op.create_index("ix_discovery_hits_status", "discovery_hits", ["status"])

    # 7. company_pages → companies, discovery_hits
    op.create_table(
        "company_pages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=False,
        ),
        sa.Column(
            "discovery_hit_id",
            UUID(as_uuid=True),
            sa.ForeignKey("discovery_hits.id"),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        # Path to HTML on disk — content is NEVER stored in the database
        sa.Column("raw_html_path", sa.Text(), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_company_pages_company_id", "company_pages", ["company_id"]
    )
    op.create_index(
        "ix_company_pages_discovery_hit_id",
        "company_pages",
        ["discovery_hit_id"],
    )

    # 8. contacts → companies
    op.create_table(
        "contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=False,
        ),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("extra_fields", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])

    # 9. emails → contacts (nullable), companies (nullable)
    op.create_table(
        "emails",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=True,
        ),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("status", _sa_enum("emailstatus"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mx_valid", sa.Boolean(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_emails_contact_id", "emails", ["contact_id"])
    op.create_index("ix_emails_company_id", "emails", ["company_id"])
    op.create_index("ix_emails_address", "emails", ["address"])

    # 10. phones → contacts (nullable), companies (nullable)
    op.create_table(
        "phones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=True,
        ),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("raw_number", sa.Text(), nullable=True),
        sa.Column("phone_type", _sa_enum("phonetype"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_phones_contact_id", "phones", ["contact_id"])
    op.create_index("ix_phones_company_id", "phones", ["company_id"])

    # 11. company_leads → companies (unique), campaigns (nullable)
    op.create_table(
        "company_leads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id"),
            nullable=True,
        ),
        sa.Column("status", _sa_enum("leadstatus"), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("score_band", _sa_enum("scoreband"), nullable=True),
        sa.Column("review_status", _sa_enum("reviewstatus"), nullable=False),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_fields", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", name="uq_company_lead_company"),
    )
    op.create_index(
        "ix_company_leads_company_id", "company_leads", ["company_id"]
    )
    op.create_index(
        "ix_company_leads_campaign_id", "company_leads", ["campaign_id"]
    )
    op.create_index("ix_company_leads_status", "company_leads", ["status"])
    op.create_index(
        "ix_company_leads_review_status", "company_leads", ["review_status"]
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # Drop tables in reverse FK dependency order
    op.drop_table("company_leads")
    op.drop_table("phones")
    op.drop_table("emails")
    op.drop_table("contacts")
    op.drop_table("company_pages")
    op.drop_table("discovery_hits")
    op.drop_table("audit_log")
    op.drop_table("suppression_list")
    op.drop_table("companies")
    op.drop_table("campaigns")

    # Drop all PostgreSQL enum types (reverse order for safety)
    conn = op.get_bind()
    for type_name, _ in reversed(_ENUM_TYPES):
        conn.execute(sa.text(f"DROP TYPE IF EXISTS {type_name}"))
