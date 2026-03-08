# Lead Discovery Platform

Automated pipeline for discovering, extracting, verifying, scoring, and exporting sales leads.

## Architecture

```
src/
├── config/       # Settings loaded from .env
├── db/           # SQLAlchemy engine, session, base
├── models/       # ORM models (Lead, Company, Source, Run, etc.)
├── discovery/    # Finding candidate URLs/sources
├── scraper/      # Fetching and storing raw HTML to disk
├── extraction/   # LLM-based field extraction from HTML
├── verification/ # Validating extracted data (email, phone, etc.)
├── scoring/      # Lead quality scoring
├── review/       # Human-in-the-loop review interface
├── export/       # CSV/CRM export
└── pipeline/     # Orchestration across stages
```

## Storage

- **PostgreSQL** — structured lead data, run metadata, status tracking
- **`data/pages/`** — raw HTML files (never stored in DB)
- **`data/llm_runs/`** — LLM prompt/response debug artifacts

## Setup

```bash
cp .env.example .env
# edit .env with your DATABASE_URL and LLM_API_KEY

pip install -e ".[dev]"

alembic upgrade head
```

## Usage

```bash
leads --help
```

## Docs

See `docs/` for Obsidian-compatible markdown notes on design decisions.
