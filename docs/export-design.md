---
title: Export Design
tags: [export, csv, suppression, outreach]
---

# Export Design

This document covers the Phase 5 export layer: how approved leads are formatted, suppression-checked, and written to CSV files.

## Export Types

Three CSV files are produced per export run, each targeting a different use case:

| File | Description |
|------|-------------|
| `contacts_<ts>.csv` | One row per named contact with an exportable email |
| `companies_<ts>.csv` | One row per company with no named-contact export but a usable company-level email or phone |
| `leads_<ts>.csv` | One row per company — management view; all companies included regardless of suppression |

## Exportability Rules

Only leads with:
- `review_status = APPROVED`
- `status NOT IN (DISQUALIFIED, CHURNED)`

…are included in the named-contacts and company-fallback files. The full-leads file always includes all APPROVED leads.

### Status × export-type matrix

| Lead Status | Named Contacts | Company Fallback | Full Leads |
|-------------|---------------|-----------------|------------|
| QUALIFIED | yes | yes | yes |
| CONTACTED | yes (unless `--only-uncontacted`) | yes | yes |
| CONVERTED | no (unless `--include-converted`) | no | yes |
| CHURNED | never | never | never |
| DISQUALIFIED | never | never | never |

## Company Fallback Eligibility

A company row appears in the `companies` file when ALL of:
1. No named contact for this company has an exportable email.
2. At least one company-level email (`contact_id IS NULL`) with `status != INVALID` exists, OR at least one company-level phone (`contact_id IS NULL`) exists.
3. The company is not suppressed.

## Suppression Checking

### `is_company_suppressed()`

Returns True if ANY of:
- `company.domain` is in the suppressed domains set
- `company.name` (case-insensitive) is in the suppressed companies set
- Any email address for the company (contact-linked or company-level) is in suppressed emails
- Domain of any email for the company is in suppressed domains

### `is_exportable_email()`

Returns False if ANY of:
- `status == INVALID`
- `address.lower()` is in suppressed emails
- Domain of address is in suppressed domains

## Output Column Schemas

### Named Contacts (`contacts_<ts>.csv`)

| Column | Description |
|--------|-------------|
| `first_name` | Contact first name (or first token of full_name) |
| `last_name` | Contact last name (or remaining tokens of full_name) |
| `email` | Best exportable email for this contact |
| `title` | Contact title |
| `company_name` | Company name |
| `website` | Company website |
| `city` | Company city |
| `country` | Company country |
| `phone` | Contact-linked E.164 phone, or blank |
| `score` | Lead quality score (1 decimal place) |
| `score_band` | hot / warm / cold |
| `lead_id` | UUID of the CompanyLead record |

### Company Fallback (`companies_<ts>.csv`)

| Column | Description |
|--------|-------------|
| `company_name` | Company name |
| `website` | Company website |
| `email` | Best company-level email |
| `phone` | Best company-level phone (E.164) |
| `address` | Company address |
| `city` | Company city |
| `country` | Company country |
| `score` | Lead quality score |
| `score_band` | hot / warm / cold |
| `lead_id` | UUID of the CompanyLead record |

### Full Leads (`leads_<ts>.csv`)

| Column | Description |
|--------|-------------|
| `company_name` | Company name |
| `website` | Company website |
| `email` | Best company-level email |
| `phone` | Best company-level phone |
| `address` | Company address |
| `city` | Company city |
| `country` | Company country |
| `score` | Lead quality score |
| `score_band` | hot / warm / cold |
| `contact_count` | Number of contacts |
| `exportable_email_count` | Count of contact emails passing `is_exportable_email()` |
| `company_email_count` | Count of company-level emails with `status != INVALID` |
| `named_contacts` | Semicolon-joined top-3 contact labels (`Full Name (Title)`) |
| `exportable_emails` | Semicolon-joined top-3 exportable contact emails |
| `review_approved_at` | ISO timestamp when review decision was made |
| `lead_id` | UUID of the CompanyLead record |
| `suppressed` | True if company is suppressed (management visibility) |

## Re-export Safety

Each export run produces new timestamped files:

```
data/exports/<campaign_id>/contacts_20260314_120000.csv
data/exports/<campaign_id>/companies_20260314_120000.csv
data/exports/<campaign_id>/leads_20260314_120000.csv
```

No state is written to the database during export. Re-running export is always safe. To prevent re-contacting leads, add emailed addresses to `suppression_list` before the next run (see [[known-risks]] — X1).

## Outreach Tracking Transitions

After export, update lead status via CLI commands to track outreach progress:

```
new → qualified (auto: on review approval)
qualified → contacted  (leads mark-contacted --lead-id <uuid>)
contacted → converted  (leads mark-converted --lead-id <uuid>)
contacted → churned    (leads mark-churned --lead-id <uuid>)
converted → churned    (leads mark-churned --lead-id <uuid>)
```

Churned leads are permanently excluded from future exports. There is no un-churn transition.

## CLI Usage Examples

```bash
# Export all approved qualified leads
leads export --campaign-id <uuid>

# Export to a custom directory
leads export --campaign-id <uuid> --output-dir /tmp/my_exports

# Exclude already-contacted leads
leads export --campaign-id <uuid> --only-uncontacted

# Include converted leads in output
leads export --campaign-id <uuid> --include-converted

# Mark a lead as contacted after outreach
leads mark-contacted --lead-id <uuid>

# Mark a lead as converted
leads mark-converted --lead-id <uuid>

# Mark a lead as churned
leads mark-churned --lead-id <uuid>

# Run pipeline stages scrape through score
leads run --campaign-id <uuid> --from-stage scrape --to-stage score

# Dry run to see what would happen
leads run --campaign-id <uuid> --dry-run
```

## Related Notes

- [[pipeline]] — stage flow and CLI command table
- [[database-schema]] — suppression_list and company_leads table definitions
- [[known-risks]] — export risks X1, X2, X3
- [[scoring-model]] — how leads are scored before review
