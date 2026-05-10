---
title: Scoring Model
tags: [scoring, lead-quality, aeo, tech-signals]
---

# Scoring Model

Every lead receives a numeric score and a score band after verification. The score drives review prioritisation and export filtering.

See [[pipeline]] for where scoring sits and [[database-schema]] for how scores are stored.

## Score Bands

| Band | Score Range | Meaning |
|------|-------------|---------|
| `HOT` | ≥ 75 | High-quality, contact-ready lead |
| `WARM` | 50–74 | Usable but incomplete or partially verified |
| `COLD` | < 50 | Poor data quality or low confidence |
| `DISQUALIFIED` | 0 | Hard disqualification (see below) |

## Hard Disqualification Rules

Applied before the score is computed. Any one of these triggers immediate disqualification:

1. `company.name` is null or empty
2. No emails **and** no phones — unless the campaign sets `require_contact=False` (used for web-search / ecommerce campaigns where contact forms are the norm)
3. Company matches an active suppression entry (domain, email, or name)

## Scoring Dimensions

The score is the sum of seven independent dimensions.

---

### A · Contact Richness (max 30)

Measures quality of named contact data.

| Signal | Points |
|--------|--------|
| ≥1 contact with `full_name` | +12 |
| ≥1 contact with `full_name` + `title` | +8 |
| ≥1 email linked to a named contact | +6 |
| ≥1 phone linked to a named contact | +4 |

---

### B · Channel Availability (max 25)

Measures what outreach channels exist.

| Signal | Points |
|--------|--------|
| ≥1 company-level email (`info@`, `contact@`, …) | +10 |
| ≥1 company-level phone | +8 |
| `company.website` is set | +7 |

---

### C · Verification Quality (max 25)

Rewards leads where data has been confirmed valid.

| Signal | Points |
|--------|--------|
| ≥1 email with status `VALID` | +10 |
| ≥1 email with a passing MX record | +5 |
| ≥1 phone with a known type (mobile / landline) | +5 |
| Company website returned a 2xx response | +5 |

---

### D · Scrape Quality (max 12)

Reflects how much page content was retrieved.

| Signal | Points |
|--------|--------|
| Any pages saved | +5 |
| ≥1 ABOUT, CONTACT, or TEAM page saved | +4 |
| ≥1 page with ≥ 50 words of extracted text | +3 |

---

### E · Location Data (max 8)

| Signal | Points |
|--------|--------|
| `address` or `city` present | +5 |
| `country` present | +3 |

---

### F · AEO Opportunity (max 15)

Higher score = more gaps in search optimisation = stronger pitch for AEO / AI-search services. Detected by [[aeo-signals]] from saved HTML — no extra network calls.

| Signal | Points |
|--------|--------|
| No JSON-LD at all | +6 |
| Has JSON-LD but no LocalBusiness/Store schema type | +3 |
| No `<meta name="viewport">` (not mobile-friendly) | +4 |
| No Open Graph tags | +3 |
| Serving over HTTP (not HTTPS) | +2 |

---

### G · Tech Gap Opportunity (max 10)

Higher score = more marketing tech gaps = stronger prospect for digital agencies pitching ads, analytics, or growth services. Detected by [[tech-signals]] from saved HTML — zero extra network calls.

| Signal | Points |
|--------|--------|
| Not running any paid ads (no Google Ads, Meta Pixel, or TikTok Pixel) | +4 |
| No Google Analytics | +2 |
| No live chat widget | +2 |
| No blog / content section | +1 |
| No cookie consent banner | +1 |

> [!tip]
> For an agency selling Google Ads management, filter the review queue by `tech_signals.google_ads = false`. For Meta Ads, filter by `meta_pixel = false`. Both signals are stored in `score_details.tech_signals`.

---

## Total Score

```
total = A + B + C + D + E + F + G   (max 125)
band  = HOT if ≥75, WARM if ≥50, else COLD
```

The maximum theoretical score is 125, but no hard cap is applied — a brand with rich contacts, verified email, a full scrape, location data, and every tech/AEO gap maxed out will score above 100.

## score_details Breakdown

Every `CompanyLead.score_details` JSON object contains:

```json
{
  "contact_richness": 20,
  "channel_availability": 17,
  "verification_quality": 15,
  "scrape_quality": 9,
  "location": 5,
  "tech_gap": 8,
  "tech_signals": {
    "google_ads": false,
    "meta_pixel": false,
    "google_analytics": true,
    "tiktok_pixel": false,
    "cms": "shopify",
    "has_chat": false,
    "has_cookie_banner": true,
    "has_blog": false,
    "has_faq": false
  },
  "aeo_opportunity": 13,
  "aeo_signals": {
    "has_json_ld": false,
    "has_local_business_schema": false,
    "has_viewport_meta": true,
    "has_og_tags": false,
    "is_https": true
  },
  "website_reachable": true,
  "total": 87
}
```

## Re-scoring

Scoring is a pure function with no network calls. Run `leads score` again at any time to recompute scores against updated weights without re-scraping or re-extracting.

## Related Notes

- [[pipeline]] — stage flow
- [[ecommerce-discovery]] — Shopify / web-search campaigns and AEO context
- [[database-schema]] — `company_leads.score`, `score_band`, `score_details` columns
