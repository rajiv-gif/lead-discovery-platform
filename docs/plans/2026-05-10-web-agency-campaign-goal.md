---
title: Web Agency Campaign Goal
date: 2026-05-10
tags: [plan, web-agency, scoring, feature-flag]
status: approved
---

# Web Agency Campaign Goal

## Problem

The existing pipeline is optimised for finding businesses with rich contact data (emails, phones, named contacts). A different market exists: web agencies that cold-pitch local businesses with no website or an outdated one. For this use case, the *absence* of a website is the strongest positive signal — the complete opposite of the current scoring logic.

This feature adds a `WEB_AGENCY` campaign goal that flips the scoring intent and filters the pipeline accordingly, without touching any existing `LEAD_GEN` behaviour.

---

## Feature Flag

Everything in this plan is gated behind:

```
WEB_AGENCY_ENABLED=true   # .env — unset by default
```

When the flag is off, the enum value exists in code but nothing in the UI, CLI, or scoring activates it. This keeps the feature invisible on the public repo until launch.

---

## Data Model Changes

### `enums.py` — new `CampaignGoal` enum

```python
class CampaignGoal(str, enum.Enum):
    LEAD_GEN   = "lead_gen"    # default — current behaviour unchanged
    WEB_AGENCY = "web_agency"  # find businesses needing a website
```

### `Campaign` model — one new column

```python
campaign_goal: Mapped[CampaignGoal] = mapped_column(
    SQLEnum(CampaignGoal),
    default=CampaignGoal.LEAD_GEN,
    nullable=False,
    server_default="lead_gen",
)
```

### `Company` model — one new column

```python
has_website: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

Set to `False` when `website_uri` is absent in the Google Places API response. No extra network call — the field is already in the Places payload.

### Migration

Single Alembic migration covering both columns. All existing rows default to `lead_gen` / `True`.

---

## Pipeline Flow

```
Discovery → [Scraper] → [Extraction] → Verification → Scoring → Review → Export
                ↑              ↑
           skip if          skip if
           no website       no website
```

| Stage | No-website business | Has-website business |
|-------|--------------------|--------------------|
| Discovery | Normal — write `has_website=False` | Normal |
| Scraper | Mark `SCRAPED` immediately, no fetch | Fetch normally |
| Extraction | Skip — no HTML to parse | Extract normally |
| Verification | Phone + address validation only | Full validation |
| Scoring | Dimension H dominates | All dimensions including H |
| Export | `website_status=none` | `website_status=outdated` or `present` |

---

## New Scoring Module: `src/scoring/website_gap.py`

### `WebsiteGapSignals` dataclass

```python
@dataclass
class WebsiteGapSignals:
    has_website: bool           # from company.has_website
    is_https: bool              # from saved HTML / AEO signals
    has_viewport: bool          # from saved HTML / AEO signals
    copyright_year_age: int     # years since copyright year in HTML (0 = not found)
    has_social_links: bool      # facebook/instagram/linkedin/twitter links in HTML
    word_count: int             # total words across saved pages
```

`detect_website_gap(company, pages, base_path)` — reads `company.has_website` and the already-saved HTML pages. Zero additional network calls.

### Dimension H — Website Gap (max 30)

| Signal | Points |
|--------|--------|
| No website at all | +30 |
| Has website but not HTTPS | +8 |
| No mobile viewport | +7 |
| Copyright year ≥ 3 years old | +7 |
| No social media links | +5 |
| Thin content (< 100 words) | +3 |

**Only applied when `campaign.campaign_goal == WEB_AGENCY`.** For `LEAD_GEN` campaigns, Dimension H is always 0.

A no-website business scores +30 on Dimension H alone. Combined with a phone number (+8 channel availability) and a passing address (+5 location), it clears the HOT threshold (≥ 75) without scraping anything.

---

## Config

```python
# config/settings.py
web_agency_enabled: bool = Field(default=False, alias="WEB_AGENCY_ENABLED")
```

---

## UI Changes

### Campaign create form

A goal pill-toggle appears at the top **only when `WEB_AGENCY_ENABLED=true`**:

```
[ Lead Gen ]  [ Web Agency ]
```

Selecting **Web Agency**:
- Locks discovery source to `Places` (web search irrelevant for local no-website hunt)
- Hides ecommerce platform field
- Relabels "Niche" → "Business type" (e.g. "restaurant", "hair salon")

### Campaign list

A small secondary badge on web agency campaigns:

```
● active   web agency   Restaurants Amsterdam   24 leads →
```

Existing lead gen campaigns show no extra badge.

### Lead review rows

A distinct `✦ No website` badge (separate colour from score bands) on no-website leads:

```
Bakkerij De Hoek   ✦ No website   HOT   Amsterdam  →
```

---

## Export

Two new columns appended to the existing CSV:

| Column | Values |
|--------|--------|
| `website_status` | `none` / `outdated` / `present` |
| `website_gap_score` | Integer (Dimension H value, 0–30) |

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `src/models/enums.py` | Add `CampaignGoal` enum |
| `src/models/campaign.py` | Add `campaign_goal` column |
| `src/models/company.py` | Add `has_website` column |
| `src/config/settings.py` | Add `web_agency_enabled` flag |
| `src/discovery/places.py` | Set `has_website` from `website_uri` |
| `src/scraper/runner.py` | Short-circuit no-website hits |
| `src/scoring/website_gap.py` | New — `WebsiteGapSignals` + `detect_website_gap()` |
| `src/scoring/scorer.py` | Add Dimension H, gated on `campaign_goal` |
| `src/scoring/deriver.py` | Wire `detect_website_gap()` into scoring |
| `src/dashboard/routes/campaigns.py` | Pass `web_agency_enabled` to templates |
| `src/dashboard/templates/campaigns/new.html` | Goal toggle |
| `src/dashboard/templates/campaigns/list.html` | Goal badge |
| `src/dashboard/templates/campaigns/detail.html` | No-website badge on leads |
| `alembic/versions/<hash>_add_campaign_goal_has_website.py` | Migration |

---

## Out of Scope (Phase 2)

- Multi-tenant agency portal / per-customer flag
- ML-based website quality scoring
- Screenshot-based visual quality detection
- Separate export template for web agencies
