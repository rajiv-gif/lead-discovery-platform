# Lead Discovery Platform

Automated pipeline for discovering, extracting, verifying, scoring, and exporting B2B sales leads.

Finds businesses via the Google Places API, scrapes their websites, extracts contacts using deterministic rules and an LLM fallback (Anthropic), verifies emails and phones, scores each lead, and exports to CSV.

---

## Pipeline stages

| Stage | Command | What it does |
|---|---|---|
| Discovery | `leads run-discovery` | Queries Google Places; upserts companies and discovery hits |
| Scrape | `leads scrape` | Fetches company websites; saves HTML to disk and metadata to DB |
| Extract | `leads extract` | Extracts contacts, emails, phones via regex rules + LLM fallback |
| Verify | `leads verify` | Validates emails (MX), classifies phones, checks website reachability |
| Score | `leads score` | Computes a 0–100 quality score per lead; writes `company_leads` rows |
| Review | `leads review` | Interactive approve / reject queue; sets `review_status` |
| Export | `leads export` | Writes three CSVs: named contacts, company fallback, full leads view |

`leads run` runs **discovery → score** in one command. **Review and export are always separate explicit steps.**

---

## Core models

| Model | Table | Purpose |
|---|---|---|
| `Campaign` | `campaigns` | Geo-targeted search configuration |
| `Company` | `companies` | Discovered business entity |
| `DiscoveryHit` | `discovery_hits` | One Places result per campaign per company |
| `CompanyPage` | `company_pages` | Scraped page (homepage / team / contact / about) |
| `Contact` | `contacts` | Named individual extracted from a page |
| `Email` | `emails` | Email address linked to company or contact |
| `Phone` | `phones` | Phone number linked to company or contact |
| `CompanyLead` | `company_leads` | Score, status, and review state per campaign per company |
| `SuppressionList` | `suppression_list` | Domains, emails, or company names to exclude from export |

---

## Prerequisites

- **Python ≥ 3.11**
- **PostgreSQL** — a running instance with a database created
- **Google Places API key** — required for the discovery stage
- **Anthropic API key** — required for LLM extraction (skipped automatically if not set)

---

## Setup

```bash
# 1. Copy and fill in environment variables
cp .env.example .env

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Run migrations
alembic upgrade head
```

Minimum required variables in `.env`:

```
DATABASE_URL=postgresql://user:password@localhost:5432/lead_discovery
GOOGLE_PLACES_API_KEY=<your-key>
ANTHROPIC_API_KEY=<your-key>
```

---

## Usage

### 1. Create a campaign

```bash
# City mode
leads create-campaign "London Dentists" \
  --geo-method city --city London --country UK --specialty dentists

# Radius mode
leads create-campaign "Central London Dentists" \
  --geo-method center_radius \
  --center-lat 51.5074 --center-lng -0.1278 --radius-m 5000
```

Save the printed campaign UUID as `$CID`.

### 2. Run the pipeline (discovery → score)

Run all pipeline stages in one command:

```bash
leads run --campaign-id $CID
```

Or run stages individually (useful for debugging or resuming):

```bash
leads run-discovery --campaign-id $CID
leads scrape        --campaign-id $CID
leads extract       --campaign-id $CID
leads verify        --campaign-id $CID
leads score         --campaign-id $CID
```

Resume from a specific stage:

```bash
leads run --campaign-id $CID --from-stage extract --to-stage score
```

### 3. Review leads

```bash
leads review --campaign-id $CID --min-score 40
```

Interactive prompt: approve, reject, or skip each lead. Approved leads transition to `QUALIFIED` status.

### 4. Export to CSV

```bash
leads export --campaign-id $CID
```

Writes three files to `data/exports/<campaign-id>/`:

| File | Contents |
|---|---|
| `contacts_<timestamp>.csv` | Named contacts with verified emails (Instantly / Smartlead compatible) |
| `companies_<timestamp>.csv` | Company-level fallback rows (no named contact with exportable email) |
| `leads_<timestamp>.csv` | Full view of all approved leads including suppression flag |

### 5. Track outreach

```bash
leads mark-contacted  --lead-id $LID
leads mark-converted  --lead-id $LID
leads mark-churned    --lead-id $LID
```

---

## Runtime artifacts

All runtime data is local and git-ignored:

| Path | Contents |
|---|---|
| `data/pages/` | Raw HTML files from scraping |
| `data/llm_runs/` | LLM prompt/response debug artifacts |
| `data/website_checks/` | Website reachability results (JSON, per campaign) |
| `data/exports/` | Exported CSV files (per campaign, timestamped) |

---

## Development

```bash
# Run all tests
pytest

# Run tests with output
pytest -v
```

See `docs/` for design notes on each stage.
