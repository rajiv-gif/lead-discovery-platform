---
title: Yelp Discovery + LinkedIn & SMTP Enrichment
date: 2026-05-13
tags: [plan, discovery, enrichment, yelp, linkedin, smtp]
status: implemented
---

# Yelp Discovery + LinkedIn & SMTP Enrichment

## Problems solved

1. **Google Places coverage gaps** — some local businesses appear on Yelp but not Places, especially in food, beauty, and retail verticals.
2. **No owner contact data** — extraction pulls emails from websites but doesn't know who the business owner is.
3. **Missing business emails** — many SMB websites don't publish a contact email. SMTP probing can confirm generic patterns (`info@`, `office@`) and name-based patterns without sending any mail.

---

## Yelp Fusion discovery (`src/discovery/yelp.py`)

### What it does

`YelpClient` wraps the Yelp Fusion Business Search and Business Details endpoints, returning the same `PlaceResult` dataclass as the Google Places client so the rest of the pipeline is source-agnostic.

### Key design decisions

**`website` vs `url` field distinction** — The Yelp API returns two URL fields:

| Field | Contains |
|-------|----------|
| `url` | Yelp listing page (e.g. `yelp.com/biz/...`) |
| `website` | Business's own website (e.g. `abcplumbing.com`) |

`_fetch_website()` deliberately ignores `url` and only returns `website`. Storing a Yelp listing URL as `company.website` would set `company.domain = "www.yelp.com"`, breaking domain-based dedup for all Yelp-sourced companies.

**Place ID namespacing** — All Yelp IDs are prefixed with `yelp:` (e.g. `yelp:abc-plumbing-chicago`) to prevent collisions with Google Place IDs.

**Detail fetches** — Each search result triggers a separate `GET /v3/businesses/{id}` call to retrieve the website URL. This doubles API usage but is necessary — the search endpoint doesn't return `website`.

### Geo method support

| Geo method | Yelp API parameter |
|------------|-------------------|
| `CITY` | `location` (city + country string) |
| `POSTAL_CODE` | `location` (postal code string) |
| `CENTER_RADIUS` | `latitude` + `longitude` + `radius` (capped at 40 km) |
| `BOUNDING_BOX` | Approximated as centre + half-diagonal radius |

### Free tier limits

- 500 search calls/day
- 500 detail calls/day
- Up to 240 results per query (50/page × 5 pages)

Set `YELP_API_KEY` in `.env` to activate.

---

## LinkedIn owner lookup (`src/enrichment/linkedin_lookup.py`)

### What it does

`find_owner(company_name, city)` searches DuckDuckGo for `site:linkedin.com/in` profiles matching the business name and owner/founder titles. Returns a `LinkedInOwner` dataclass with name, title, LinkedIn URL, and confidence level.

No LinkedIn credentials or API key required — uses DuckDuckGo's public HTML endpoint.

### Owner title matching

Titles are matched with word-boundary regex (`\b`) to prevent false positives:

| Pattern | Matches | Does not match |
|---------|---------|----------------|
| `owner` | "Owner" | "sub-owner" (edge case) |
| `director` | Only in "Managing Director" | "Art Director", "Director of Photography" |
| `principal` | Not included | "Principal Engineer", "Principal Consultant" |
| `operator` | Not included | "Machine Operator", "Forklift Operator" |

### Confidence levels

| Level | Source | Condition |
|-------|--------|-----------|
| `high` | Title string | Owner title found in `Name - Title - Company \| LinkedIn` |
| `medium` | Snippet | Owner title found in `Name · Title at Company` |

### City fallback gate

`city_fallback=False` by default. When enabled via `LINKEDIN_CITY_FALLBACK_ENABLED=true`, a second query without the city constraint fires if the city-scoped query returns nothing. High recall, but higher false-positive rate for common business names.

### Rate limiting

DuckDuckGo blocks aggressive scraping. Default delay: 2 s between requests. Not suitable for bulk runs > 100 companies/hour.

---

## SMTP email probing (`src/enrichment/smtp_prober.py`)

### What it does

`probe_domain(domain, contacts)` generates candidate email addresses and verifies them via SMTP RCPT TO — no message is ever sent.

### Candidate generation

For each domain, two pools are generated:

1. **Generic prefixes** — `info@`, `office@`, `contact@`, `hello@`, `reception@`, `appointments@`, `front@`, `admin@`
2. **Contact-based patterns** — derived from `(first_name, last_name)` tuples extracted by the LLM:
   - `{first}.{last}@`, `{fi}{last}@`, `dr{last}@`, `dr.{last}@`, `{first}@`, `dr{first}@`

### Catch-all detection

Before probing real candidates, a canary address (`canary_xzqq_99999@domain`) is sent. If the server accepts it, every address would be accepted — results are flagged `CATCH_ALL` rather than `VALID`.

### Free domain filtering

Common consumer domains (Gmail, Yahoo, Outlook, iCloud, etc.) are skipped entirely — no MX lookup, no SMTP connection.

### Limitations

- Port 25 is blocked by many ISPs and cloud providers (Railway, AWS, GCP). `probe_domain` returns `[]` gracefully when port 25 is unreachable.
- Catch-all servers inflate apparent email validity.
- Best-effort only — confirmed addresses ≠ inbox deliverability.

---

## New files

| File | Purpose |
|------|---------|
| `src/discovery/yelp.py` | Yelp Fusion API client → `PlaceResult` |
| `src/enrichment/__init__.py` | Package marker |
| `src/enrichment/linkedin_lookup.py` | DuckDuckGo LinkedIn owner search |
| `src/enrichment/smtp_prober.py` | SMTP RCPT TO email verification |
| `tests/discovery/test_yelp.py` | 24 unit tests for `YelpClient` |
| `tests/enrichment/test_linkedin_lookup.py` | 48 unit tests for `find_owner` |

---

## Related

- [[2026-05-13-playwright-browser-fallback]] — browser fallback for bot-protected pages (same sprint)
- [[2026-05-13-volume-and-llm-routing]] — LLM routing and volume scaling
- `src/discovery/places.py` — Google Places client (shared `PlaceResult` interface)
