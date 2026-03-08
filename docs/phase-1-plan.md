---
title: Phase 1 Plan
tags: [planning, phase-1, milestones]
---

# Phase 1 Plan

Phase 1 builds the core pipeline end-to-end with a single source type and a minimal review interface. The goal is a working vertical slice — not completeness.

See [[architecture]] for the module map and [[pipeline]] for stage definitions.

## Scope

### In Scope

- [x] Project scaffolding and folder structure
- [x] Documentation (this docs folder)
- [ ] `src/config/` — env loading with validation
- [ ] `src/db/` — SQLAlchemy engine, session, declarative base
- [ ] `src/models/` — `Run`, `Source`, `Lead`, `ExtractionRun` ORM models
- [ ] Alembic migration for initial schema
- [ ] `src/scraper/` — basic HTTP fetch, HTML saved to disk
- [ ] `src/extraction/` — LLM call with structured output, debug artifacts
- [ ] `src/verification/` — email format + MX, phone parsing
- [ ] `src/scoring/` — weighted score calculation
- [ ] `src/review/` — CLI review loop (approve / reject / skip)
- [ ] `src/export/` — CSV export of approved leads
- [ ] `src/pipeline/` — `run` command that chains all stages
- [ ] `src/discovery/` — manual seed input (CSV of URLs) as the first adapter
- [ ] Typer CLI with sub-commands for each stage

### Out of Scope (Phase 2+)

- Automated discovery (Google Maps API, scraping directories)
- LinkedIn adapter
- Web-based review UI
- CRM integrations (HubSpot, Salesforce)
- Email deliverability checks (SMTP probing)
- Re-extraction on HTML change detection
- Fine-tuning or custom models
- Multi-user / team workflow

## Milestones

### M1 — Foundation

> Config, DB, models, migrations working. Can connect to PostgreSQL and create schema.

- [ ] `src/config/settings.py` loads and validates all env vars
- [ ] `src/db/` exposes `engine`, `Session`, `Base`
- [ ] All four ORM models defined
- [ ] `alembic init` + initial migration
- [ ] `alembic upgrade head` creates schema cleanly

---

### M2 — Scraper

> Can take a list of URLs and save HTML to disk with DB metadata.

- [ ] `leads scrape --input urls.txt` runs without error
- [ ] HTML files appear in `data/pages/`
- [ ] `source` records created with correct status and `page_path`
- [ ] Failed fetches marked `status=failed` and do not crash the run

---

### M3 — Extraction

> LLM reads HTML from disk and produces a `Lead` record.

- [ ] `leads extract` processes all `fetched` sources
- [ ] Returns valid JSON matching the field schema
- [ ] Writes prompt + response to `data/llm_runs/`
- [ ] `extraction_run` record saved with token counts and latency
- [ ] Partial / failed extractions handled gracefully

See [[extraction-strategy]] for prompt and schema details.

---

### M4 — Verification + Scoring

> Leads have validated fields and a numeric score.

- [ ] Email field validated (format + MX lookup)
- [ ] Phone normalized to E.164
- [ ] Website reachability checked
- [ ] Duplicate detection against existing approved leads
- [ ] Score computed per [[scoring-model]]
- [ ] Score band assigned

---

### M5 — Review + Export

> A human can review leads in the terminal and export approved ones to CSV.

- [ ] `leads review` shows one lead at a time: approve / reject / skip
- [ ] Review decision and optional note saved to `lead.review_status`
- [ ] `leads export --output leads.csv` writes approved leads
- [ ] CSV includes all core fields in a consistent column order

---

### M6 — Pipeline Integration

> All stages chain together with a single command.

- [ ] `leads run --input urls.txt` runs all stages in order
- [ ] `Run` record tracks counts per stage
- [ ] A failed stage logs the error and stops cleanly (does not corrupt data)
- [ ] `leads run --from-stage extract` resumes from a given stage

---

## Definition of Done (Phase 1)

Phase 1 is complete when:

1. `leads run --input urls.txt` processes a batch of 50 URLs end-to-end
2. At least 30 leads reach the review queue
3. Approved leads export to a clean CSV
4. All tests in `tests/` pass
5. Schema is managed entirely through Alembic migrations

## Testing Strategy

- Unit tests for scoring (pure function, no DB)
- Unit tests for verification (no network — use mocks for MX/HTTP)
- Integration tests for extraction using a fixture HTML file and mocked LLM
- End-to-end smoke test with a small seed file against a real local DB

## Related Notes

- [[architecture]] — module responsibilities
- [[pipeline]] — stage-by-stage detail
- [[database-schema]] — tables being built in M1
- [[extraction-strategy]] — M3 implementation guide
- [[scoring-model]] — M4 implementation guide
