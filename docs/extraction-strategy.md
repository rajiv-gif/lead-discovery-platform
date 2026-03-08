---
title: Extraction Strategy
tags: [extraction, llm, prompting]
---

# Extraction Strategy

The extraction stage takes raw HTML from disk and uses an LLM to produce structured lead data. This document covers the prompting approach, output schema, failure handling, and debug artifact format.

See [[pipeline]] for where extraction fits in the overall flow and [[database-schema]] for how results are stored.

## Goal

Given a scraped business listing or company page, extract a fixed set of lead fields as structured JSON — reliably, without hallucination, and with graceful degradation when fields are missing.

## Field Target Schema

The LLM is asked to return this JSON structure:

```json
{
  "company_name": "string or null",
  "website": "string or null",
  "email": "string or null",
  "phone": "string or null",
  "address": "string or null",
  "city": "string or null",
  "state": "string or null",
  "country": "string or null",
  "industry": "string or null",
  "description": "string or null",
  "linkedin_url": "string or null",
  "extra": {}
}
```

`extra` captures any additional useful fields that don't map to the fixed schema (e.g. `founded_year`, `employee_count`).

## Prompting Approach

### System Prompt

The system prompt establishes the model's role and output constraints:

- Extract only what is explicitly present in the HTML — do not infer or fabricate
- Return `null` for any field not found
- Output must be valid JSON matching the schema — no prose, no markdown
- Phone numbers should be returned as-found; verification normalizes them later

### User Prompt

The user message contains:

1. The source URL (for context)
2. A cleaned excerpt of the HTML (not the full raw page)

HTML is pre-processed before being sent to the LLM:
- Script, style, and nav tags stripped
- Whitespace collapsed
- Truncated to a maximum token budget (configurable, default ~8k tokens)

> [!warning]
> Never send raw unprocessed HTML to the LLM. Token waste and extraction quality both suffer significantly.

### Model Choice

The default model is configurable via `LLM_MODEL` in `.env`. Recommended:

| Use case | Model |
|----------|-------|
| Production | `gpt-4o` — best accuracy on messy HTML |
| Development / cost control | `gpt-4o-mini` — faster, cheaper, slightly less reliable |

## Structured Output

Where supported, use the LLM provider's **structured output / JSON mode** to guarantee schema-conforming responses. For providers without native structured output, enforce JSON via prompt and validate with a schema checker on response.

## Failure Handling

Extraction can fail at several points:

| Failure | Handling |
|---------|----------|
| LLM API error / timeout | Retry up to 3× with exponential backoff |
| Response not valid JSON | Log artifact, mark `extraction_status = failed` |
| All fields null | Mark `extraction_status = failed` (blank response is useless) |
| Partial extraction | Accept — missing fields are null, verification flags them |

A failed extraction does **not** block the pipeline. The `Source` record is marked failed and skipped in downstream stages.

## Debug Artifacts

Every LLM call writes two files to `data/llm_runs/`:

```
data/llm_runs/
└── <extraction_run_id>/
    ├── prompt.json      # full messages array sent to API
    └── response.json    # raw API response object
```

`prompt.json` format:
```json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "source_url": "https://...",
  "source_id": "uuid"
}
```

`response.json` format:
```json
{
  "id": "chatcmpl-...",
  "model": "gpt-4o",
  "usage": {"prompt_tokens": 1200, "completion_tokens": 180},
  "choices": [{"message": {"content": "{...}"}}],
  "latency_ms": 1420
}
```

These files are gitignored and stay local. The `extraction_run` table stores the paths and token counts.

## Quality Signals

During extraction, record signals that feed into [[scoring-model]]:

- Number of non-null fields returned
- Whether `email` and `phone` were present
- LLM confidence (if the model supports it)
- Whether `extra` contains useful bonus fields

## Future Considerations

- **Multi-pass extraction:** Run a second, focused prompt for fields the first pass missed
- **Per-source-type prompts:** Directory listings vs. company homepages need different prompts
- **Caching:** Skip re-extraction if the HTML hasn't changed (compare hash)
- **Fine-tuning:** Collect confirmed extractions to fine-tune a cheaper model

## Related Notes

- [[pipeline]] — extraction stage in context
- [[database-schema]] — `lead` and `extraction_run` tables
- [[scoring-model]] — how extraction quality feeds into the score
