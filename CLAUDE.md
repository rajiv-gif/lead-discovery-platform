# Lead Discovery Platform — Claude Context

## Project Summary

Python CLI pipeline that discovers leads by scraping web pages, extracting structured data with an LLM, verifying and scoring the results, then exporting to CSV or CRM.

## Key Rules

- **Raw HTML lives on disk** (`data/pages/`), never in PostgreSQL
- **LLM debug artifacts** (prompts, raw responses) go in `data/llm_runs/`
- **PostgreSQL** stores only structured, processed data via SQLAlchemy ORM
- Migrations are managed with **Alembic** — always generate a migration when changing models
- CLI is built with **Typer**; entry point is `leads` (defined in `pyproject.toml`)
- Config is loaded from `.env` via `python-dotenv`; never hardcode credentials

## Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `config/` | Load and validate env settings |
| `db/` | Engine, session factory, declarative base |
| `models/` | SQLAlchemy ORM models |
| `discovery/` | Finding candidate URLs or data sources |
| `scraper/` | HTTP fetch → save HTML to `data/pages/` |
| `extraction/` | LLM call → structured fields from HTML |
| `verification/` | Email/phone/URL validation |
| `scoring/` | Lead quality score |
| `review/` | Human review CLI or UI |
| `export/` | CSV / CRM output |
| `pipeline/` | Stage orchestration |

## Testing

```bash
pytest
```

## Docs

`docs/` contains Obsidian-compatible markdown. Use `[[wikilinks]]` freely.
