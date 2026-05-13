---
title: Playwright Browser Fallback
date: 2026-05-13
tags: [plan, scraper, playwright, bot-protection]
status: implemented
---

# Playwright Browser Fallback

## Problem solved

A significant portion of SMB websites are protected by Cloudflare, require JavaScript rendering (React/Vue SPAs), or actively fingerprint and reject plain HTTP scrapers. The standard `httpx`-based fetcher fails on these sites with 403, 503, or returns an empty JS shell — meaning those leads never get scraped and remain stuck in `failed` status.

---

## Solution

A headless Chromium fallback via `playwright` that activates automatically when the HTTP fetcher struggles. The standard HTTP path always runs first — Playwright only kicks in as a secondary attempt.

---

## Trigger conditions (`should_try_playwright`)

| Condition | Why |
|-----------|-----|
| HTTP 403 or 503 | Bot-blocking gate |
| Cloudflare challenge markers in HTML | JS challenge page (not real content) |
| 200 but HTML < 1 500 chars | JS shell — React/Vue SPA with no SSR |

429 (rate limit) does **not** trigger Playwright — it's a transient error best handled by backing off.

---

## Implementation

### New file: `src/scraper/playwright_fetcher.py`

- `should_try_playwright(result: FetchResult) → bool` — detects the trigger conditions above
- `fetch_with_playwright(url, timeout=20.0) → FetchResult` — headless Chromium, same `FetchResult` interface as the HTTP fetcher
  - Blocks images, fonts, media, stylesheets (HTML only — faster)
  - Waits for `networkidle` so JS-rendered content is fully populated
  - Graceful `ImportError` if the `browser` extra is not installed

### `src/scraper/runner.py`

Added `_playwright_fallback(url, result)` helper — a one-liner gating check — wired at three points:

1. Homepage fetch
2. Root domain fallback fetch (when the deep URL fails)
3. Each supplemental page fetch

### `src/config/settings.py`

| Setting | Env var | Default |
|---------|---------|---------|
| `playwright_enabled` | `PLAYWRIGHT_ENABLED` | `false` |
| `playwright_timeout` | `PLAYWRIGHT_TIMEOUT` | `20.0` s |

### `pyproject.toml`

```toml
[project.optional-dependencies]
browser = ["playwright>=1.44"]
```

Activation:
```bash
pip install "lead-discovery[browser]"
playwright install chromium
```

Then set `PLAYWRIGHT_ENABLED=true` in `.env`.

---

## What this covers

| Scenario | Before | After |
|----------|--------|-------|
| Cloudflare-protected SMB sites | `failed` | Scraped via real browser |
| React/Vue SPA (JS shell) | Extracted from empty HTML | Full rendered DOM |
| Standard accessible sites | HTTP (fast) | HTTP (unchanged) |
| True 429 rate limits | `failed` | Still `failed` (Playwright won't help) |

---

## What this does NOT cover

- CAPTCHA-gated pages — Playwright doesn't solve them
- Login-required pages — no credentials available
- Sites that require human-like behaviour over multiple sessions

For those edge cases, manual review is the right path.

---

## Related

- [[2026-05-13-volume-and-llm-routing]] — broader scraper and LLM changes from this sprint
- `src/scraper/fetcher.py` — base HTTP fetcher and `FetchResult` dataclass
