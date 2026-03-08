# Domain Models Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace placeholder ORM scaffolding with the full Phase 1 domain model — 10 tables with proper enums, FKs, relationships, and an Alembic migration.

**Architecture:** All models use SQLAlchemy 2.0 `Mapped`/`mapped_column` style with UUID PKs and shared mixins. Enums are defined once in `src/models/enums.py` and mapped to native PostgreSQL enum types. The Alembic migration is hand-written (no live DB required for generation) and creates all enum types before tables.

**Tech Stack:** SQLAlchemy 2.0, Alembic 1.13, PostgreSQL, Python 3.11 enums, psycopg2

---

## File Map

```
src/models/
├── mixins.py            (exists — keep)
├── enums.py             (NEW)
├── campaign.py          (NEW, replaces run.py)
├── company.py           (NEW)
├── discovery_hit.py     (NEW, replaces source.py)
├── company_page.py      (NEW)
├── contact.py           (NEW)
├── email.py             (NEW)
├── phone.py             (NEW)
├── company_lead.py      (NEW, replaces lead.py)
├── audit_log.py         (NEW, replaces extraction_run.py)
├── suppression_list.py  (NEW)
└── __init__.py          (UPDATE)

alembic/versions/
└── 20260308_<rev>_initial_domain_schema.py  (NEW)
```

**Delete:** `src/models/run.py`, `source.py`, `lead.py`, `extraction_run.py`

---

## Enum Reference

| Enum name (PostgreSQL) | Values |
|------------------------|--------|
| `campaignstatus` | draft, active, paused, completed, archived |
| `discoveryhitstatus` | pending, scraped, extracted, failed, skipped |
| `discoveryhitsourcetype` | google_maps, directory, manual, linkedin, web_search |
| `emailstatus` | unverified, valid, invalid, catch_all, risky |
| `phonetype` | mobile, office, direct, fax, unknown |
| `leadstatus` | new, qualified, disqualified, contacted, converted, churned |
| `reviewstatus` | pending, approved, rejected, needs_edit |
| `scoreband` | hot, warm, cold, disqualified |
| `auditaction` | INSERT, UPDATE, DELETE |
| `suppressiontype` | email, domain, company, phone |
| `suppressionreason` | unsubscribed, bounced, spam_complaint, do_not_contact, competitor, manual |

---

## Table Dependency Order

Creation order (FK deps):
1. `campaigns` — no deps
2. `companies` — no deps
3. `suppression_list` — no deps
4. `audit_log` — no deps (generic ref via table_name + record_id)
5. `discovery_hits` → campaigns, companies
6. `company_pages` → companies, discovery_hits
7. `contacts` → companies
8. `emails` → contacts (nullable), companies (nullable)
9. `phones` → contacts (nullable), companies (nullable)
10. `company_leads` → companies (unique), campaigns (nullable)

---

### Task 1: Remove obsolete scaffolding models

**Files:** Delete `src/models/run.py`, `source.py`, `lead.py`, `extraction_run.py`

```bash
git rm src/models/run.py src/models/source.py src/models/lead.py src/models/extraction_run.py
```

---

### Task 2: Create `src/models/enums.py`

All Python enums in one place. SQLAlchemy models import from here.

```python
import enum

class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"; ACTIVE = "active"; PAUSED = "paused"
    COMPLETED = "completed"; ARCHIVED = "archived"

class DiscoveryHitStatus(str, enum.Enum):
    PENDING = "pending"; SCRAPED = "scraped"; EXTRACTED = "extracted"
    FAILED = "failed"; SKIPPED = "skipped"

class DiscoveryHitSourceType(str, enum.Enum):
    GOOGLE_MAPS = "google_maps"; DIRECTORY = "directory"; MANUAL = "manual"
    LINKEDIN = "linkedin"; WEB_SEARCH = "web_search"

class EmailStatus(str, enum.Enum):
    UNVERIFIED = "unverified"; VALID = "valid"; INVALID = "invalid"
    CATCH_ALL = "catch_all"; RISKY = "risky"

class PhoneType(str, enum.Enum):
    MOBILE = "mobile"; OFFICE = "office"; DIRECT = "direct"
    FAX = "fax"; UNKNOWN = "unknown"

class LeadStatus(str, enum.Enum):
    NEW = "new"; QUALIFIED = "qualified"; DISQUALIFIED = "disqualified"
    CONTACTED = "contacted"; CONVERTED = "converted"; CHURNED = "churned"

class ReviewStatus(str, enum.Enum):
    PENDING = "pending"; APPROVED = "approved"
    REJECTED = "rejected"; NEEDS_EDIT = "needs_edit"

class ScoreBand(str, enum.Enum):
    HOT = "hot"; WARM = "warm"; COLD = "cold"; DISQUALIFIED = "disqualified"

class AuditAction(str, enum.Enum):
    INSERT = "INSERT"; UPDATE = "UPDATE"; DELETE = "DELETE"

class SuppressionType(str, enum.Enum):
    EMAIL = "email"; DOMAIN = "domain"; COMPANY = "company"; PHONE = "phone"

class SuppressionReason(str, enum.Enum):
    UNSUBSCRIBED = "unsubscribed"; BOUNCED = "bounced"
    SPAM_COMPLAINT = "spam_complaint"; DO_NOT_CONTACT = "do_not_contact"
    COMPETITOR = "competitor"; MANUAL = "manual"
```

---

### Task 3: Create the 10 model files

Each file imports from `src.db.base`, `src.models.mixins`, `src.models.enums`.
All use `UUIDPrimaryKey` + `TimestampMixin` except `AuditLog` (no `updated_at`).

Key design notes per model:

**campaigns** — `name`, `description`, `status: CampaignStatus`

**companies** — `name`, `website`, `domain` (extracted, indexed), `industry`, `description`, `linkedin_url`, `address/city/state/country`, `employee_count`, `founded_year`, `extra_fields: JSON`

**discovery_hits** — FK: `campaign_id` (required), `company_id` (nullable, set post-extraction); `source_url`, `source_type: DiscoveryHitSourceType`, `status: DiscoveryHitStatus`, `fetched_at`, `http_status_code`; unique constraint on `(campaign_id, source_url)`

**company_pages** — FK: `company_id` (required), `discovery_hit_id` (nullable); `url`, **`raw_html_path`** (path on disk — never store HTML in DB), `content_hash` (SHA-256 for change detection), `fetched_at`, `http_status_code`

**contacts** — FK: `company_id`; `first_name`, `last_name`, `full_name`, `title`, `linkedin_url`, `source`, `extra_fields: JSON`

**emails** — FK: `contact_id` (nullable), `company_id` (nullable); `address` (indexed), `status: EmailStatus`, `is_primary: bool`, `mx_valid: bool | None`, `verified_at`

**phones** — FK: `contact_id` (nullable), `company_id` (nullable); `number` (E.164 after normalization), `raw_number` (as-extracted), `phone_type: PhoneType`, `is_primary: bool`, `verified_at`

**company_leads** — FK: `company_id` (unique — 1:1 with company), `campaign_id` (nullable); `status: LeadStatus`, `score: float | None`, `score_band: ScoreBand | None`, `review_status: ReviewStatus`, `reviewer_notes`, `qualified_at`, `contacted_at`, `converted_at`, `extra_fields: JSON`

**audit_log** — NO `updated_at`; generic ref: `table_name`, `record_id: UUID`, `action: AuditAction`, `changed_by`, `old_values: JSON`, `new_values: JSON`; composite index on `(table_name, record_id)`

**suppression_list** — `type: SuppressionType`, `value` (indexed), `reason: SuppressionReason`, `notes`, `expires_at`; unique constraint on `(type, value)`

---

### Task 4: Update `src/models/__init__.py`

```python
from src.models.campaign import Campaign
from src.models.company import Company
from src.models.discovery_hit import DiscoveryHit
from src.models.company_page import CompanyPage
from src.models.contact import Contact
from src.models.email import Email
from src.models.phone import Phone
from src.models.company_lead import CompanyLead
from src.models.audit_log import AuditLog
from src.models.suppression_list import SuppressionList

__all__ = [
    "Campaign", "Company", "DiscoveryHit", "CompanyPage",
    "Contact", "Email", "Phone", "CompanyLead", "AuditLog", "SuppressionList",
]
```

---

### Task 5: Write the Alembic migration

File: `alembic/versions/20260308_a1b2c3d4e5f6_initial_domain_schema.py`

Pattern for enum creation (do before all tables):
```python
op.execute(sa.text("CREATE TYPE campaignstatus AS ENUM ('draft','active','paused','completed','archived')"))
```

Pattern for table creation:
```python
op.create_table('campaigns',
    sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum(..., name='campaignstatus', create_type=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
)
```

Downgrade: drop tables in reverse order, then `DROP TYPE IF EXISTS` all enum types.

---

### Task 6: Commit

```bash
git add src/models/ alembic/
git commit -m "feat: implement full domain model with Alembic migration"
```
