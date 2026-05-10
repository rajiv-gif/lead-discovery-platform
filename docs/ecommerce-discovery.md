---
title: Ecommerce Discovery
tags: [discovery, ecommerce, shopify, web-search, serper, aeo, tech-signals]
---

# Ecommerce / Web-Search Discovery

A parallel discovery track for finding ecommerce leads instead of local businesses. Uses **Serper.dev** (Google-backed, 100 results/query) when `SERPER_API_KEY` is set, or falls back to DuckDuckGo (free, ~10 results/query).

See [[pipeline]] for where discovery fits and [[scoring-model]] for AEO + tech signal scoring.

---

## When to Use

| Campaign type | Use this when… |
|---------------|----------------|
| Local Business (Places) | Target is a physical-location business — dentist, plumber, restaurant, etc. |
| Ecommerce / Web Search | Target is an online store, DTC brand, or any non-location business |

---

## How It Works

```
Campaign.discovery_source = web_search
Campaign.search_queries   = ["luxury fashion online store", "premium streetwear brand"]
Campaign.ecommerce_platform = "shopify"  ← optional

  → web_runner.py loops queries
  → SerperClient (preferred) or DuckDuckGoClient POSTs search request
  → Deduplicates by domain across all queries
  → Upserts Company (domain as key; no google_place_id)
  → Creates DiscoveryHit (source_type = WEB_SEARCH)
  → [Shopify mode only] fetches /products.json → extra_fields enrichment
```

---

## Search Providers

### Serper.dev (recommended)

Set `SERPER_API_KEY` in `.env` to enable. Returns up to **100 organic results per query** using Google's index — dramatically better coverage than DuckDuckGo for niche markets.

- Paginates in pages of 10 (Serper rejects `num=100` for complex queries)
- No rate limiting needed (managed by Serper)
- ~$50/mo for 50k queries; free tier available

### DuckDuckGo (free fallback)

Used automatically when `SERPER_API_KEY` is not set.

- POST to `https://html.duckduckgo.com/html/` with `q=<query>`
- Parses `div.result`, `a.result__a` (URL + title), `a.result__snippet`
- Rate-limited at 2 seconds per query
- Returns ~10 results per query

> [!warning]
> DuckDuckGo's HTML structure can change without notice — this is an unofficial scrape. If discovery returns 0 results, check the DDG HTML response for structural changes.

---

## Domain Skip List

Both clients filter results against `_SKIP_DOMAINS` — a 50+ entry list of non-lead domains:

- Social media (Facebook, Instagram, LinkedIn, TikTok, …)
- Big retail (Amazon, eBay, Etsy, …)
- B2B directories (Clutch, Crunchbase, ZoomInfo, Apollo, G2, …)
- Shopify aggregators (FindNiche, myip.ms, …)

Add to this list in `src/discovery/web_search.py` if aggregator sites keep appearing.

---

## Shopify Mode

Set `ecommerce_platform = shopify` on the campaign to activate:

### 1. Query rewriting
`"cdn.shopify.com"` is appended to every search query so search engines surface stores on **custom domains** (paid plans) as well as free `*.myshopify.com` stores.

### 2. Fast path for `.myshopify.com` results
Results on the `.myshopify.com` domain are already confirmed Shopify — homepage detection is skipped and `/products.json` enrichment runs immediately.

### 3. Homepage fingerprint gate (custom domains)
`_enrich_shopify()` GETs the store homepage and runs `detect_shopify()` first. Results that don't pass the HTML fingerprint check are dropped as false positives.

`detect_shopify(html)` checks for any of:
- `cdn.shopify.com`
- `Shopify.shop`
- `shopify-section`
- `/cdn/shop/`
- `name="shopify-`
- `window.Shopify`

### 4. Products.json enrichment
`fetch_shopify_info()` GETs `/products.json?limit=250` and extracts:
- `shopify_product_count` — number of active products
- `shopify_price_min` / `shopify_price_max` — price range across variants (EUR)
- `shopify_myshopify_url` — permanent `*.myshopify.com` backend URL

All stored in `company.extra_fields`.

---

## Shopify Scraper Strategy

Because `.myshopify.com` backend URLs are aggressively rate-limited by Shopify's CDN (HTTP 429), the scraper uses a three-step fallback for confirmed Shopify stores:

1. **`/pages/contact`** — static, rarely rate-limited, contains email/phone/address for the LLM
2. **Store homepage** (`<store>.myshopify.com`) — if contact page 404s
3. **Synthetic fallback** — a minimal HTML page built from `/products.json` metadata; no network call, but also no contact info

This is implemented in `_scrape_shopify_store()` in `src/scraper/runner.py`.

---

## LLM Extraction

The extraction stage uses a **local Ollama model** (default: `qwen2.5:7b`) to extract contact info from scraped pages. Configure in `.env`:

```
OLLAMA_BASE_URL=http://<your-machine>:11434
OLLAMA_MODEL=qwen2.5:7b
```

`qwen2.5:7b` is recommended over thinking models (like `gemma4:e2b`) for this task — it produces reliable JSON and responds in 5–30 seconds per page. An Anthropic API key (`ANTHROPIC_API_KEY`) can be used as an alternative when Ollama is not available.

---

## Deduplication

| Scope | Key | Mechanism |
|-------|-----|-----------|
| Within a single run | `domain` | `seen_domains` set in `web_runner.py` |
| Across runs / campaigns | `domain` | `Company.domain` unique lookup in `upsert_company_from_web_search()` |

No `google_place_id` is used for web-search companies. Domain is the sole dedup key.

---

## Scoring for Ecommerce Leads

The scoring pipeline is identical to the Places flow — all 7 dimensions apply. `require_contact=False` is set for web-search campaigns so that stores with no public email/phone aren't immediately disqualified (they use contact forms).

Typical Shopify store profile:

| Dimension | Typical range | Notes |
|-----------|--------------|-------|
| Contact Richness (A) | 0–12 | DTC brands rarely expose founder names publicly |
| Channel Availability (B) | 17–25 | Website always set; contact page often has email |
| AEO Opportunity (F) | 9–15 | Shopify themes often lack JSON-LD; OG tags are generic |
| Tech Gap (G) | 4–10 | Many small stores have no Google Ads or analytics |

**HOT Shopify leads (≥ 75)** = stores with a contact email, verified MX, strong AEO gaps, and missing ad tech. Ideal pitch targets for AI-search and paid advertising services.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SERPER_API_KEY` | — | Enables Serper.dev (100 results/query). Unset = DDG |
| `RESPECT_ROBOTS_TXT` | `true` | Set `false` to bypass robots.txt (advisory only) |
| `SCRAPER_RATE_LIMIT_DELAY` | `1.0` | Seconds between fetches to the same domain |
| `OLLAMA_BASE_URL` | — | Ollama server URL (e.g. `http://192.168.1.10:11434`) |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Model to use for extraction |
| `HUNTER_API_KEY` | — | Enables Hunter.io personal email enrichment |

---

## Related Notes

- [[pipeline]] — stage flow, discovery dispatch
- [[scoring-model]] — AEO (F) and tech gap (G) dimensions
- [[database-schema]] — `campaigns` ecommerce columns, `companies.extra_fields` Shopify keys
- [[architecture]] — module map
