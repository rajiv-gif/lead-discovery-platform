---
title: Scoring Model
tags: [scoring, lead-quality]
---

# Scoring Model

Every lead receives a numeric score (0–100) and a score band after verification. The score drives review prioritization and export filtering.

See [[pipeline]] for where scoring sits and [[database-schema]] for how scores are stored.

## Score Bands

| Band | Score Range | Meaning |
|------|-------------|---------|
| `hot` | 75–100 | High-quality, contact-ready lead |
| `warm` | 50–74 | Usable but incomplete or partially verified |
| `cold` | 25–49 | Poor data quality, low confidence |
| `disqualified` | 0–24 | Missing critical fields or failed verification |

Leads below a configurable minimum score threshold (default: 25) are excluded from the review queue entirely.

## Scoring Dimensions

The score is a weighted sum across four dimensions:

### 1. Field Completeness (max 35 points)

Measures what fraction of key fields are present. Core fields carry more weight than secondary fields.

| Field | Points |
|-------|--------|
| `company_name` | 10 |
| `email` | 8 |
| `phone` | 6 |
| `website` | 5 |
| `address` / `city` | 4 (2 each) |
| `industry` | 2 |

Partial credit: a field that is present but failed verification scores 50% of its point value.

---

### 2. Verification Quality (max 30 points)

Rewards leads where extracted data has been confirmed valid.

| Signal | Points |
|--------|--------|
| Email passes format + MX check | 12 |
| Phone parses to valid E.164 | 8 |
| Website returns 2xx response | 6 |
| No duplicate match found | 4 |

---

### 3. Source Quality (max 20 points)

Reflects the reliability of the data source. Configured per source type.

| Source Type | Points |
|-------------|--------|
| Verified directory (e.g. industry association) | 20 |
| Google Maps / local listing | 15 |
| LinkedIn company page | 12 |
| General web scrape | 8 |
| Manual / unknown | 5 |

---

### 4. Extraction Confidence (max 15 points)

Rewards leads where the LLM returned rich, complete output.

| Signal | Points |
|--------|--------|
| 8+ non-null fields returned | 10 |
| 5–7 non-null fields | 6 |
| 3–4 non-null fields | 3 |
| `extra` fields present | 5 (bonus) |

> [!note]
> The 5 bonus points from `extra` can push a lead above 100. The score is capped at 100.

## Score Calculation

```
score = field_completeness + verification_quality + source_quality + extraction_confidence
score = min(score, 100)
score_band = band(score)
```

## Score Band Assignment

```
score >= 75  → hot
score >= 50  → warm
score >= 25  → cold
score <  25  → disqualified
```

## Tuning

Weights should be revisited after reviewing the first 200+ leads. Key questions:

- Are `hot` leads actually converting?
- Are `cold` leads being wrongly discarded?
- Does source quality correlate with real-world usefulness?

Scoring logic lives in `src/scoring/` as a pure function with no DB side effects — it can be re-run against existing leads without re-scraping or re-extracting.

## Disqualification Rules

A lead is **automatically disqualified** (score = 0, band = `disqualified`) if any of the following are true:

- `company_name` is null
- Both `email` and `phone` are null
- The lead is a duplicate of an already-approved lead

These are hard rules applied before the weighted score is computed.

## Related Notes

- [[pipeline]] — where scoring sits in the flow
- [[extraction-strategy]] — extraction confidence signals
- [[database-schema]] — `lead.score`, `lead.score_band` columns
- [[phase-1-plan]] — scoring is a phase 1 deliverable
