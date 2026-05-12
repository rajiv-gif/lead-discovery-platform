---
title: Volume Scaling + LLM Routing
date: 2026-05-13
tags: [plan, tiling, query-expansion, llm, settings]
status: implemented
---

# Volume Scaling + LLM Routing

## Problems solved

1. **Low volume on bounding-box campaigns** — a single Places API call returns at most 60 results, capping local-business campaigns regardless of area size.
2. **Slow extraction at scale** — local LLM processes one page every 5–10 s; large campaigns (Netherlands HVAC) could take hours.
3. **No LLM provider abstraction** — extraction and query expansion were not sharing the same client factory, making future provider switching hard.
4. **Geography confusion on web-search campaigns** — state/multi-city UI was broken and conceptually wrong for ecommerce discovery.

---

## Changes shipped

### Bounding-box grid tiling (`src/discovery/strategies.py`)

`_bounding_box_queries()` now tiles the bounding box into a grid of circle queries when `campaign.geo_tile_size_km` is set.

- Each tile becomes an independent `circle` restriction passed to Places API
- Tile radius = half the tile side + 5% overlap to eliminate gaps
- Coordinate maths: flat-earth approximation (accurate at city/country scale)
- Legacy single-query path preserved when `geo_tile_size_km` is None

**Chicago HVAC example:**
- 3 km tiles → 180 tiles × 3 pages = 540 API calls ≈ $17, est. 400–700 unique businesses
- 2 km tiles → 396 tiles × 3 pages = 1,188 API calls ≈ $38, est. 500–800 unique businesses

### Places query variants (`campaigns.places_query_variants`)

New JSONB column. Extra niche terms (e.g. `["air conditioning", "furnace repair"]`) each generate the full tile grid independently. Dedup by `google_place_id` prevents duplicates in the DB.

Combined with tiling, two variants on a 3 km Chicago grid = ~1,080 API calls, est. 600–900 unique leads.

### Live cost/estimate widget

Pure-JS estimate bar on the bounding-box form section. Updates as coordinates and tile size change:

```
180 tiles × 2 queries × 3 pages = 1,080 API calls · ~$35 · est. 270–720 unique businesses
```

### LLM client factory (`src/extraction/llm.py`)

New `get_llm_client()` function centralises provider selection (Ollama → Anthropic → None). All modules now call this instead of duplicating the selection logic.

### Per-stage extraction provider (`src/config/settings.py`, `src/config/runtime.py`)

`EXTRACTION_PROVIDER` env var + dashboard Settings toggle decouples extraction from query expansion:

| Stage | Default | Override |
|-------|---------|---------|
| Query expansion | Local LLM | Always local (free, fast for short prompts) |
| Extraction | Local LLM | `EXTRACTION_PROVIDER=anthropic` for large campaigns (~$0.001/page, ~0.5 s/page) |

Runtime config written to `data/leadry_config.json` — takes effect on next run, no restart needed.

### Dashboard Settings page (`/settings`)

New page with extraction provider toggle (Local / Haiku). Shows which providers are configured, warns if a key is missing.

### Query expansion for web search (`src/discovery/query_expansion.py`)

LLM generates 7 alternative phrasings from a single seed query. Displayed inline on the campaign create form via HTMX — user can edit or remove before submitting. Uses `get_llm_client()` factory (local first).

`POST /campaigns/expand-queries` endpoint returns a textarea partial swapped in by HTMX.

### Geography cleanup

- Removed state/multi-city geo method (broken, wrong model for Places)
- Removed `search_geo_scope` field from web-search form — geography belongs in the query itself (e.g. `"HVAC Chicago"`)
- Backend `search_geo_scope` column retained for future programmatic use

---

## New DB columns

| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| `campaigns` | `geo_tile_size_km` | `FLOAT` | Tile side length for bounding-box grid |
| `campaigns` | `places_query_variants` | `JSONB` | Extra niche terms for Places campaigns |
| `campaigns` | `search_geo_scope` | `TEXT` | (Reserved) geo append for web search |

Migrations: `20260511_688f1b33f9de`, `20260512_86f4acea0834`

---

## New files

| File | Purpose |
|------|---------|
| `src/config/runtime.py` | Read/write `data/leadry_config.json` for live config overrides |
| `src/discovery/query_expansion.py` | LLM query expansion for web-search campaigns |
| `src/dashboard/routes/settings_routes.py` | `/settings` page |
| `src/dashboard/templates/settings.html` | Settings page UI |
| `src/dashboard/templates/campaigns/_query_textarea.html` | HTMX partial for query list |

---

## Related

- [[2026-05-11-query-expansion-filters]] — original design doc for query expansion
- [[2026-05-10-web-agency-campaign-goal]] — WEB_AGENCY goal that benefits from tiling
- [[2026-05-10-autonomous-agent]] — agent loop that will orchestrate tiled campaigns
