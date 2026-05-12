---
title: Query Expansion + Revenue & Geography Filters
date: 2026-05-11
tags: [plan, web-search, shopify, filters, query-expansion]
status: implemented
implemented: 2026-05-13
---

# Query Expansion + Revenue & Geography Filters

## Problem

A single web-search campaign query (e.g. `"luxury fashion Shopify stores"`) returns at most ~100 Serper results. Campaigns that ran 400+ hits used Google Maps (Places API), which returns results per geographic tile. Web-search has no equivalent breadth mechanism — a single query is a single API call.

Two consequences:
1. **Low volume** — 28 hits for luxury fashion vs 400 for Places-backed campaigns.
2. **Narrow coverage** — one phrasing misses stores that don't use those exact words in their web presence.

The fix has three parts built in order of impact.

---

## Part 1 — Query Expansion

### Core Idea

When the user types a niche (e.g. `"luxury fashion Shopify stores"`), an LLM generates 6–8 semantically distinct query variations before the campaign is created. Each variation becomes a separate Serper API call. With 8 queries × 100 results = **800 candidate URLs**, deduplication by domain drops this to ~300–400 unique stores.

### Where it happens

**Inline on the campaign create form** — the user sees the expanded queries before submitting, can delete ones they don't want, and can add their own. The final list is stored on the campaign and used by the discovery runner.

### Data model

```sql
-- New column on campaigns
search_queries   TEXT[]   -- ordered list; index 0 is the original user query
```

This replaces the single `search_query TEXT` column (backwards-compatible: existing campaigns have a 1-element array).

**Migration**: `ALTER TABLE campaigns ADD COLUMN search_queries TEXT[] DEFAULT '{}'::text[]`.  
Backfill: `UPDATE campaigns SET search_queries = ARRAY[search_query] WHERE search_queries IS NULL OR search_queries = '{}'`.

### LLM expansion call

Triggered by a new `POST /campaigns/expand-queries` endpoint, called via HTMX when the user pauses typing (300ms debounce) or clicks "Expand".

**Prompt** (sent to `claude-haiku-3-5` — fast, cheap):

```
You are helping a lead generation researcher find more results.

Original query: "{user_query}"
Campaign goal: {campaign_goal}   # "shopify_stores" | "web_agency" | "lead_gen"

Generate 7 alternative search queries that would find similar businesses
using different phrasings. Rules:
- Each must be a valid Google search query (short, no prose)
- Vary vocabulary: "store" vs "shop" vs "boutique", "luxury" vs "premium" vs "high-end"
- Try brand-name adjacent terms, niche subcategories, geographic modifiers if relevant
- Do NOT repeat the original query
- Return as a JSON array of strings, nothing else

Example output:
["premium fashion online store", "luxury clothing boutique site", ...]
```

**Response parsed** as `list[str]`. Validation: strip empty strings, cap at 8, deduplicate.

### UI flow

```
Campaign create form
─────────────────────────────────────────────────────────────
Niche / Search query
[ luxury fashion Shopify stores              ] [Expand ↗]
                                                    ↓ HTMX POST
Queries to run (drag to reorder, × to remove)
  1. luxury fashion Shopify stores          ×   (original)
  2. premium fashion online store           ×
  3. high-end clothing boutique site        ×
  4. luxury apparel ecommerce shop          ×
  5. designer clothing Shopify              ×
  6. upscale fashion brand online           ×
  7. luxury women's fashion store           ×
  8. premium boutique clothing shop         ×
  [+ Add custom query]

Max results per query  [ 100 ] (Serper free: 100/query)
─────────────────────────────────────────────────────────────
```

Queries are serialised as `search_queries[]` form fields and stored on the campaign.

### Discovery runner change

`src/discovery/web_search.py` — current loop:
```python
results = serper_search(campaign.search_query, n=100)
```

New loop:
```python
all_results = []
for query in campaign.search_queries:
    results = serper_search(query, n=campaign.max_results_per_query)
    all_results.extend(results)
```

Deduplication by domain happens in `upsert_company_from_web_search` (already keyed on domain — no change needed).

`DiscoveryHit.discovery_query` already stores the per-hit query string — no schema change.

---

## Part 2 — Shopify Revenue Proxy Filter

### Core Idea

Shopify stores expose product count and price range on their JSON API (`/products.json?limit=250`). This data is already scraped and stored in `company.extra_fields` as:

```json
{
  "shopify_product_count": 45,
  "shopify_price_min": 120.0,
  "shopify_price_max": 890.0,
  "platform": "shopify"
}
```

A filter on the campaign lets the user set a **minimum price floor** and **minimum product count** to target stores above a certain commercial scale. This is applied at the **scoring** stage (not scrape time), so no API calls are wasted — it's a disqualification flag.

### Data model

```sql
-- New columns on campaigns (all nullable — filter only applied when set)
shopify_min_price        NUMERIC(10,2)  -- filter: ignore stores below this unit price
shopify_min_product_count INT           -- filter: ignore stores with fewer products
```

### Scoring integration

In `src/scoring/scorer.py`, add a disqualification check at the top of `score_lead()`:

```python
# Shopify revenue proxy filter
if campaign.shopify_min_price is not None:
    price_max = (company.extra_fields or {}).get("shopify_price_max")
    if price_max is not None and price_max < campaign.shopify_min_price:
        return LeadScore(score=0, score_band=ScoreBand.DISQUALIFIED,
                         disqualification_reason="shopify_price_below_threshold")

if campaign.shopify_min_product_count is not None:
    product_count = (company.extra_fields or {}).get("shopify_product_count")
    if product_count is not None and product_count < campaign.shopify_min_product_count:
        return LeadScore(score=0, score_band=ScoreBand.DISQUALIFIED,
                         disqualification_reason="shopify_product_count_below_threshold")
```

Non-Shopify companies pass through unaffected (no `extra_fields.platform == "shopify"`).

### UI — campaign create form

Only shown when campaign goal is `shopify_stores` (future goal) or when the user has typed a query containing "shopify":

```
Shopify filters  (optional)
  Min price (highest product price)  [ $    ]
  Min product count                  [      ]
  Leave blank to include all stores.
```

---

## Part 3 — Geography Scoping

### Core Idea

Append a country or city to every expanded query. `"luxury fashion Shopify stores"` + `"Netherlands"` → `"luxury fashion Shopify stores Netherlands"`. Simple, zero-infra.

For Places campaigns (geo is already handled by lat/lng grid) this has no effect.

### Data model

```sql
-- New column on campaigns
search_geo_scope   TEXT   -- e.g. "Netherlands", "Amsterdam", "Western Europe"
```

### Append logic

In the discovery runner, before each Serper call:

```python
effective_query = query
if campaign.search_geo_scope:
    effective_query = f"{query} {campaign.search_geo_scope}"
results = serper_search(effective_query, n=campaign.max_results_per_query)
```

The stored `DiscoveryHit.discovery_query` records the **effective** (appended) query so the audit trail is correct.

### UI

One field below the query list:

```
Geography scope  (optional)
[ Netherlands                    ]
Appended to every query. Leave blank for global.
```

---

## New Module: `src/discovery/query_expansion.py`

```python
"""LLM-powered query expansion for web-search campaigns."""
from __future__ import annotations

import json
import logging
from anthropic import Anthropic

log = logging.getLogger(__name__)

_SYSTEM = "You are a search query specialist for lead generation research."

def expand_queries(
    original_query: str,
    campaign_goal: str,
    n: int = 7,
    client: Anthropic | None = None,
) -> list[str]:
    """Return up to *n* alternative queries for *original_query*.

    Falls back to [original_query] on any API error so the campaign can
    always be created even if Claude is unavailable.
    """
    client = client or Anthropic()
    prompt = _build_prompt(original_query, campaign_goal, n)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        candidates = json.loads(raw)
        if not isinstance(candidates, list):
            raise ValueError("expected list")
        result = [q for q in candidates if isinstance(q, str) and q.strip()]
        return result[:n]
    except Exception as exc:
        log.warning("Query expansion failed (%s); using original only.", exc)
        return []


def _build_prompt(query: str, goal: str, n: int) -> str:
    return (
        f'Original query: "{query}"\n'
        f"Campaign goal: {goal}\n\n"
        f"Generate {n} alternative Google search queries that would find similar "
        "businesses using different phrasings. Rules:\n"
        "- Each must be a short, valid Google search query\n"
        "- Vary vocabulary and angle (subcategory, brand-adjacent, synonym)\n"
        "- Do NOT repeat the original query\n"
        "Return ONLY a JSON array of strings."
    )
```

---

## New Dashboard Endpoint

```python
# POST /campaigns/expand-queries
# Body: query=str, campaign_goal=str
# Returns: HTML fragment (HTMX target = #query-list)
@router.post("/campaigns/expand-queries")
async def expand_queries_endpoint(
    request: Request,
    query: str = Form(...),
    campaign_goal: str = Form("lead_gen"),
):
    from src.discovery.query_expansion import expand_queries
    extras = expand_queries(query, campaign_goal)
    all_queries = [query] + extras  # original always first
    return templates.TemplateResponse(
        "campaigns/_query_list.html",
        {"request": request, "queries": all_queries},
    )
```

The `_query_list.html` partial renders the draggable list with hidden inputs:
```html
{% for q in queries %}
<div class="query-row">
  <input type="hidden" name="search_queries" value="{{ q }}">
  <span>{{ loop.index }}. {{ q }}</span>
  <button type="button" onclick="this.closest('.query-row').remove()">×</button>
</div>
{% endfor %}
```

---

## Build Order

| Step | What | Effort |
|------|------|--------|
| 1 | Migration: add `search_queries[]`, `search_geo_scope`, `shopify_min_price`, `shopify_min_product_count` to `campaigns` | Small |
| 2 | `src/discovery/query_expansion.py` | Small |
| 3 | `POST /campaigns/expand-queries` endpoint + `_query_list.html` partial | Small |
| 4 | Update campaign create form with query list UI + geo scope field | Medium |
| 5 | Update discovery runner to iterate `search_queries` + append geo scope | Small |
| 6 | Add Shopify filter disqualification to scorer | Small |
| 7 | Add Shopify filter fields to campaign create form (conditional) | Small |

Total: ~1 day of focused work. Steps 1–5 alone (query expansion + geo) deliver the volume fix with no scoring changes.

---

## Expected Impact

| Metric | Before | After (8 queries) |
|--------|--------|--------------------|
| Serper calls per campaign | 1 | 8 |
| Raw results | ~100 | ~800 |
| Unique domains (after dedup) | ~80 | ~350–500 |
| Serper cost per campaign | $0.01 | $0.08 |

Serper free tier: 2,500 searches/month. At 8 queries/campaign, that's ~312 campaigns/month before hitting the limit — well above typical usage.

---

## Related Notes

- [[pipeline]] — web_search discovery stage
- [[2026-05-10-web-agency-campaign-goal]] — WEB_AGENCY goal that benefits from higher volume
- [[2026-05-10-autonomous-agent]] — agent loop that will orchestrate expanded campaigns
