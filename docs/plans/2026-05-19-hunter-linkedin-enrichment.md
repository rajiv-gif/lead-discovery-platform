---
title: Hunter.io + LinkedIn Enrichment Integration
date: 2026-05-19
tags: [plan, enrichment, hunter, linkedin, email]
status: implemented
---

# Hunter.io + LinkedIn Enrichment Integration

## Problem solved

The extraction stage pulls emails from scraped website HTML — but most SMB websites only publish generic addresses (`info@`, `contact@`, `hello@`). Sales outreach to generic inboxes has low reply rates. The goal is to find **personal emails** like `firstname.lastname@company.com` tied to the actual business owner or decision-maker.

---

## Architecture

Three enrichment sources run in sequence per company, each building on the previous:

```
Company domain
    │
    ├─ 1. Hunter.io domain search   → all emails Hunter knows for the domain
    ├─ 2. Hunter.io email finder    → targeted lookup if contact names are known
    ├─ 3. LinkedIn owner lookup     → finds owner name via DuckDuckGo (optional)
    └─ 4. SMTP pattern probing      → generates + verifies address patterns directly
```

All sources write to the same `emails` and `contacts` tables — the pipeline stage after enrichment sees a unified list regardless of source.

---

## Hunter.io (`src/enrichment/hunter.py`)

### Two endpoints used

| Endpoint | What it does |
|----------|-------------|
| `domain-search` | Returns all emails Hunter has indexed for a domain, with type (`personal`/`generic`), confidence score, name, title, LinkedIn URL |
| `email-finder` | Given a name + domain, predicts and verifies the email address |

### Confidence filtering

`HUNTER_MIN_CONFIDENCE=70` (default) — only stores emails Hunter rates 70+ out of 100. Raise to 90 for higher precision with fewer results.

### Personal email flow

For each company:
1. `domain_search(domain)` — catches all known emails including personal ones
2. For each named contact already in the DB, `email_finder(domain, first, last)` — targeted lookup
3. Results with `email_type="personal"` automatically create a `Contact` record with name, title, LinkedIn URL from Hunter's data

### Graceful degradation

Returns `[]` (never raises) when:
- API key is absent
- Domain has no Hunter data
- Monthly quota is exhausted (429)
- Network error

---

## LinkedIn owner lookup (`src/enrichment/linkedin_lookup.py`)

Disabled by default (`LINKEDIN_LOOKUP_ENABLED=false`) — adds ~2s per company and can hit DuckDuckGo rate limits at scale. Enable when running smaller campaigns where owner contact quality matters more than speed.

When enabled, the found owner's name is fed into Hunter `email_finder` and SMTP probing to generate personalised address candidates.

---

## SMTP probing (`src/enrichment/smtp_prober.py`)

Runs for every company regardless of Hunter results. Generates `info@`, `office@`, `contact@` etc. plus name-based patterns (`first.last@`, `flast@`) and confirms them via SMTP RCPT TO — no message sent.

Useful for domains Hunter doesn't have data on (newer/smaller businesses).

---

## Settings reference

| Env var | Default | Purpose |
|---------|---------|---------|
| `HUNTER_API_KEY` | — | Hunter.io API key (required to activate Hunter enrichment) |
| `HUNTER_MIN_CONFIDENCE` | `70` | Minimum confidence score to store a Hunter email |
| `LINKEDIN_LOOKUP_ENABLED` | `false` | Enable DuckDuckGo LinkedIn owner search |
| `LINKEDIN_LOOKUP_DELAY` | `2.0` | Seconds between DDG requests |
| `LINKEDIN_CITY_FALLBACK_ENABLED` | `false` | Retry without city if city-scoped query returns nothing |
| `LINKEDIN_SMTP_HIGH_CONFIDENCE_ONLY` | `true` | Only use LinkedIn names for SMTP if confidence is "high" |

---

## What shows up in the export

After enrichment, each lead in the CSV export gains:
- Personal email(s) with `source=hunter` and confidence score
- Contact record with name, title, LinkedIn URL (when Hunter or LinkedIn found one)
- Generic verified emails from SMTP probing (`source=smtp`)

---

## Pricing

| Plan | Searches/month | Cost | Good for |
|------|---------------|------|---------|
| Free | 25 | $0 | Testing |
| Starter | 500 | $49/mo | Campaigns up to ~500 companies |
| Growth | 2,500 | $99/mo | Large campaigns |

One Hunter "search" = one `domain_search` call. `email_finder` calls count separately.

---

## Bug fixes in this session

- `src/scoring/website_gap.py` — `page.page_path` → `page.raw_html_path` (attribute name mismatch was crashing scoring for every company)

---

## Related

- [[2026-05-13-yelp-and-enrichment]] — Yelp discovery + initial enrichment module design
- `src/enrichment/runner.py` — orchestrates all three sources per company
