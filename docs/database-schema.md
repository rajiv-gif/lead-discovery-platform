---
title: Database Schema
tags: [database, schema, postgresql]
---

# Database Schema

All structured data is stored in PostgreSQL via SQLAlchemy ORM. Raw HTML and LLM artifacts are stored on disk — see [[architecture]] for the storage split.

## Entity Relationship

```mermaid
erDiagram
    RUN {
        uuid id PK
        timestamp started_at
        timestamp ended_at
        string status
        jsonb stage_counts
    }

    SOURCE {
        uuid id PK
        uuid run_id FK
        string url
        string source_type
        string status
        string page_path
        int status_code
        timestamp fetched_at
        timestamp created_at
    }

    LEAD {
        uuid id PK
        uuid source_id FK
        string company_name
        string website
        string email
        string phone
        string address
        string city
        string state
        string country
        string industry
        string description
        string linkedin_url
        jsonb extra_fields
        string extraction_status
        string verification_status
        float score
        string score_band
        string review_status
        string reviewer_notes
        timestamp created_at
        timestamp updated_at
    }

    EXTRACTION_RUN {
        uuid id PK
        uuid source_id FK
        uuid lead_id FK
        string model
        string prompt_path
        string response_path
        int prompt_tokens
        int completion_tokens
        float latency_ms
        timestamp created_at
    }

    RUN ||--o{ SOURCE : "contains"
    SOURCE ||--o| LEAD : "produces"
    SOURCE ||--o{ EXTRACTION_RUN : "has"
    LEAD ||--o{ EXTRACTION_RUN : "created by"
```

## Tables

### `run`

Tracks a single pipeline execution.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | Auto-generated |
| `started_at` | TIMESTAMP | When the run began |
| `ended_at` | TIMESTAMP | Null until complete |
| `status` | VARCHAR | `running`, `completed`, `failed` |
| `stage_counts` | JSONB | `{stage: {attempted, succeeded, failed}}` |

---

### `source`

A URL to be or already scraped.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `run_id` | UUID FK → `run` | Which run discovered this |
| `url` | TEXT | Unique per run |
| `source_type` | VARCHAR | `google_maps`, `directory`, `manual`, etc. |
| `status` | VARCHAR | `pending`, `fetched`, `failed` |
| `page_path` | TEXT | Relative path to HTML on disk |
| `status_code` | INT | HTTP response code |
| `fetched_at` | TIMESTAMP | |
| `created_at` | TIMESTAMP | |

> [!note]
> `page_path` stores a relative path like `data/pages/abc123.html`. The HTML content itself is never stored in the DB.

---

### `lead`

One extracted lead per source (1:1 in normal flow).

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `source_id` | UUID FK → `source` | |
| `company_name` | TEXT | |
| `website` | TEXT | |
| `email` | TEXT | |
| `phone` | TEXT | Stored in E.164 format after verification |
| `address` | TEXT | |
| `city` | TEXT | |
| `state` | TEXT | |
| `country` | TEXT | Default: inferred from source |
| `industry` | TEXT | |
| `description` | TEXT | Short company description |
| `linkedin_url` | TEXT | |
| `extra_fields` | JSONB | Overflow for source-specific fields |
| `extraction_status` | VARCHAR | `pending`, `extracted`, `failed` |
| `verification_status` | VARCHAR | `pending`, `verified`, `partial`, `failed` |
| `score` | FLOAT | 0.0–100.0 |
| `score_band` | VARCHAR | `hot`, `warm`, `cold`, `disqualified` |
| `review_status` | VARCHAR | `pending`, `approved`, `rejected`, `needs_edit` |
| `reviewer_notes` | TEXT | Optional human notes |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | Auto-updated |

---

### `extraction_run`

Metadata about each LLM call. The actual prompts and responses are on disk.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `source_id` | UUID FK → `source` | |
| `lead_id` | UUID FK → `lead` | Null if extraction failed |
| `model` | VARCHAR | e.g. `gpt-4o` |
| `prompt_path` | TEXT | Relative path to `data/llm_runs/` |
| `response_path` | TEXT | Relative path to `data/llm_runs/` |
| `prompt_tokens` | INT | |
| `completion_tokens` | INT | |
| `latency_ms` | FLOAT | |
| `created_at` | TIMESTAMP | |

---

## Status Progressions

```
source.status:       pending → fetched → failed
lead.extraction_status:  pending → extracted → failed
lead.verification_status: pending → verified | partial | failed
lead.review_status:  pending → approved | rejected | needs_edit
```

## Indexes

- `source(run_id)` — filter sources by run
- `source(status)` — find pending sources quickly
- `lead(source_id)` — join source → lead
- `lead(review_status, score)` — review queue ordering
- `lead(email)` — deduplication lookups

## Migrations

All schema changes go through Alembic. Never alter tables manually.

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Related Notes

- [[architecture]] — why raw HTML stays off-database
- [[pipeline]] — how each stage writes to these tables
- [[extraction-strategy]] — what fields are extracted and how
