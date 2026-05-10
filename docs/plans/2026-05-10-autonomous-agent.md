---
title: Autonomous Lead Discovery Agent
date: 2026-05-10
tags: [plan, agent, autonomous, scheduling, feedback-loop]
status: draft
---

# Autonomous Lead Discovery Agent

## Problem

The current pipeline requires a human to trigger every stage, review every lead, and decide what to run next. This limits throughput to however much time the operator has. The goal is to make the system run itself — discovering leads, learning from feedback, and graduating to full autonomy on niches it has proven it understands.

---

## Core Idea: Earn Autonomy Niche by Niche

The agent does not start fully autonomous. It earns the right to operate without human review by demonstrating it understands what the operator wants in a given niche and geography. This prevents the system from confidently surfacing the wrong leads at scale.

```
Phase 1 — Learning      Phase 2 — Assisted       Phase 3 — Autonomous
─────────────────────   ──────────────────────   ───────────────────────
Agent runs pipeline  →  Agent auto-approves   →  Agent runs end-to-end
Human reviews all       HOT leads in proven       No review needed
Agent watches           niches; human reviews     Human only notified
decisions               WARM + new niches         of weekly summary
```

Graduation is per **(niche × geography)** pair, not per campaign. "Restaurants in Amsterdam" can be autonomous while "Lawyers in Berlin" is still learning.

---

## Feedback Signal

**Primary: review decisions** — approve / reject / needs-edit, plus optional reviewer notes.
These are already captured in `company_leads.review_status` and `review_notes`.

**Secondary: outreach outcomes** — contacted / converted / churned, already tracked via `mark_contacted` / `mark_converted` / `mark_churned`. Fed into long-term confidence calculations.

**No external signal required** to get started. The agent learns entirely from what the operator already does inside the platform.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent Loop (scheduled)                   │
│                                                              │
│  1. Analyse     2. Plan          3. Execute    4. Graduate   │
│  ──────────     ──────────       ──────────    ──────────    │
│  Read niche     LLM decides      Run pipeline  Auto-approve  │
│  profiles +     which campaigns  stages for    leads that    │
│  recent         to run, pause,   active        meet niche    │
│  outcomes       or launch next   campaigns     threshold     │
│                                                              │
│  5. Report      6. Sleep                                     │
│  ──────────     ──────────                                   │
│  Notify         Wait for next                                │
│  operator of    scheduled run                                │
│  queue + stats  (configurable)                               │
└─────────────────────────────────────────────────────────────┘
         ▲
         │  reads + writes
         ▼
  PostgreSQL (existing schema + 2 new tables)
```

### Two layers of intelligence

| Layer | What it does | Implemented as |
|-------|-------------|----------------|
| **Rules engine** | Schedule runs, apply graduation thresholds, decide auto-approve vs queue | Deterministic Python |
| **LLM reasoner** | Suggest new niches, explain why a campaign underperformed, decide what to explore next | Claude API (claude-3-5-haiku) |

The LLM only handles open-ended decisions. Everything measurable (confidence scores, approval rates, thresholds) is deterministic. This keeps costs low and behaviour predictable.

---

## New Data Model

### `niche_profiles` table

Tracks per-(niche × geography) performance across all campaigns. This is the agent's memory.

```sql
niche_profiles
──────────────
id                  UUID  PK
niche               TEXT  -- "restaurants", "dentists", "hair salons"
geo_key             TEXT  -- "amsterdam:nl", "berlin:de" — normalized
campaigns_run       INT   default 0
leads_found         INT   default 0
hot_count           INT   default 0
approved_count      INT   default 0
rejected_count      INT   default 0
contacted_count     INT   default 0
converted_count     INT   default 0
confidence_score    FLOAT default 0.0  -- 0.0–1.0, see formula below
phase               TEXT  -- "learning" | "assisted" | "autonomous"
last_run_at         TIMESTAMPTZ
created_at          TIMESTAMPTZ
updated_at          TIMESTAMPTZ
```

### `agent_runs` table

One row per autonomous loop execution. The agent's audit log.

```sql
agent_runs
──────────
id                  UUID  PK
started_at          TIMESTAMPTZ
completed_at        TIMESTAMPTZ
campaigns_run       INT
leads_found         INT
leads_auto_approved INT
leads_queued        INT
llm_decisions       JSONB  -- reasoning traces from the LLM planner
summary_text        TEXT   -- human-readable summary sent in notification
error               TEXT   -- null on success
```

### Additions to existing tables

| Table | New column | Purpose |
|-------|-----------|---------|
| `campaigns` | `agent_managed BOOL default false` | Distinguishes agent-owned campaigns from manually created ones |
| `campaigns` | `agent_run_id UUID FK` | Links to the agent run that created this campaign |
| `company_leads` | `auto_approved BOOL default false` | Flags leads approved without human review |
| `company_leads` | `auto_approved_at TIMESTAMPTZ` | When auto-approval happened |

---

## Confidence Score Formula

```
confidence = (approved / (approved + rejected)) × min(1, total_reviewed / 20)
```

- Starts at 0.0 — no data, no confidence
- Grows as more leads are reviewed in this niche
- The `min(1, total_reviewed / 20)` term means confidence can't exceed 1.0 until at least 20 leads have been reviewed (prevents premature graduation on tiny samples)
- Decays slowly over time if the niche hasn't been run recently (staleness penalty)

### Phase thresholds (configurable via `.env`)

| Phase | Confidence threshold | Minimum reviewed |
|-------|---------------------|-----------------|
| `learning` | < 0.65 | any |
| `assisted` | ≥ 0.65 | ≥ 20 |
| `autonomous` | ≥ 0.85 | ≥ 50 |

---

## The Agent Loop (Step by Step)

### Step 1 — Analyse

Read all `niche_profiles` and recent `agent_runs`. Compute:
- Which niches are in `assisted` or `autonomous` phase
- Which active campaigns have pending leads waiting for review
- Which campaigns finished with zero leads (possible signal to try different geo or niche)
- Overall pipeline health (scrape failure rate, LLM extraction rate)

### Step 2 — Plan (LLM)

The LLM receives a structured context object:

```json
{
  "top_niches": [
    { "niche": "restaurants", "geo": "amsterdam:nl", "confidence": 0.87, "phase": "autonomous", "hot_rate": 0.34 },
    { "niche": "dentists",    "geo": "amsterdam:nl", "confidence": 0.71, "phase": "assisted",   "hot_rate": 0.28 }
  ],
  "underperforming": [
    { "niche": "lawyers", "geo": "berlin:de", "campaigns_run": 3, "leads_found": 4, "hot_rate": 0.0 }
  ],
  "operator_goal": "find local businesses needing AEO services",
  "budget_remaining_this_week": 3
}
```

It returns a structured plan:

```json
{
  "continue": ["restaurants:amsterdam:nl", "dentists:amsterdam:nl"],
  "pause":    ["lawyers:berlin:de"],
  "launch":   [
    { "niche": "physiotherapists", "geo": "amsterdam:nl", "reason": "similar profile to dentists, untested" }
  ],
  "reasoning": "Lawyers in Berlin had 3 runs with near-zero HOT rate; pausing. Physiotherapists share the local-service profile with dentists which is performing well."
}
```

The LLM reasoning is stored verbatim in `agent_runs.llm_decisions` for auditability.

### Step 3 — Execute

For each campaign the planner said to run:
1. Run `discovery → scrape → extract → verify → score` (existing pipeline)
2. Update `niche_profiles` with new counts

### Step 4 — Graduate

For each scored lead, check its niche profile:

```python
if niche_profile.phase == "autonomous":
    lead.review_status = ReviewStatus.APPROVED
    lead.auto_approved = True
    lead.auto_approved_at = now()
elif niche_profile.phase == "assisted" and lead.score_band == ScoreBand.HOT:
    lead.review_status = ReviewStatus.APPROVED
    lead.auto_approved = True
else:
    # stays PENDING — goes into human review queue
    pass
```

### Step 5 — Report

Compose a summary and send it to the operator:
- X leads auto-approved across Y niches
- Z leads queued for your review
- Any new niches that graduated this run
- Any niches paused by the planner
- Link to the review queue

Delivery: email (SMTP) or a webhook (Slack, Discord, ntfy.sh — operator's choice).

### Step 6 — Sleep

Wait for the next scheduled run. Default: daily at 07:00 local time. Configurable via `AGENT_SCHEDULE` in `.env`.

---

## Safety Guardrails

These cannot be overridden by the LLM planner — they are enforced by the rules engine.

| Guardrail | Default | Config key |
|-----------|---------|-----------|
| Max campaigns per agent run | 5 | `AGENT_MAX_CAMPAIGNS_PER_RUN` |
| Max leads auto-approved per day | 100 | `AGENT_MAX_AUTO_APPROVALS_PER_DAY` |
| Minimum confidence for auto-approve | 0.65 | `AGENT_MIN_CONFIDENCE_ASSISTED` |
| Minimum reviews before graduation | 20 | `AGENT_MIN_REVIEWS_FOR_GRADUATION` |
| Hard pause if scrape failure rate > X% | 50% | `AGENT_MAX_SCRAPE_FAILURE_RATE` |
| Require human approval for any new niche | always | hardcoded |

**New niches always start in `learning` phase**, even if the LLM is confident. The operator must see at least one batch before any auto-approval can happen.

---

## New Module: `src/agent/`

```
src/agent/
├── __init__.py
├── loop.py          — main agent loop orchestrator
├── planner.py       — LLM planner: builds context, calls Claude, parses plan
├── analyser.py      — reads DB, computes niche health, formats context
├── graduation.py    — applies confidence thresholds, auto-approves leads
├── notifier.py      — composes + sends run summary (email / webhook)
└── scheduler.py     — Railway cron entry point / manual trigger
```

### CLI additions

```bash
leads agent-run          # trigger one agent loop iteration manually
leads agent-status       # show niche profiles + phase for all niches
leads agent-pause        # pause all autonomous activity (emergency stop)
leads agent-graduate     # force-recalculate confidence scores
```

---

## Operator Goal Setting

The agent needs to know what kind of leads matter to the operator. This is set once in the dashboard under Settings → Agent Goal. It's passed verbatim to the LLM planner as context.

Examples:
- *"Find local service businesses (dentists, restaurants, plumbers) in the Netherlands that need AEO and AI search optimisation services"*
- *"Find Shopify stores in Western Europe with no Google Ads running — pitch is paid advertising management"*
- *"Find local businesses with no website in Amsterdam for a web agency that builds AI-generated sites"*

This single text field shapes every LLM planning decision without requiring complex configuration.

---

## Phased Build Plan

This is a significant feature. Build order to get value at each step:

| Phase | What it delivers | Effort |
|-------|-----------------|--------|
| **1 — Scheduler** | Pipeline runs automatically on a cron; no human trigger needed | Small |
| **2 — Niche profiles** | Track performance per niche; dashboard shows what's working | Medium |
| **3 — Graduation + auto-approve** | HOT leads in proven niches bypass review queue | Medium |
| **4 — LLM planner** | Agent decides what to run next; operator just reads summaries | Large |
| **5 — Notifications** | Run summaries delivered via email/webhook | Small |
| **6 — Full autonomy** | Operator sets goal once; agent runs indefinitely | Polish |

Phase 1 alone (scheduler) is valuable and low-risk. Each subsequent phase adds intelligence but Phase 1–3 can be built entirely without LLM calls.

---

## Environment Variables

```
# Agent scheduling
AGENT_ENABLED=false                   # master on/off switch
AGENT_SCHEDULE=0 7 * * *              # cron expression (daily 07:00)
AGENT_OPERATOR_GOAL=                  # plain-text goal statement

# Graduation thresholds
AGENT_MIN_CONFIDENCE_ASSISTED=0.65
AGENT_MIN_CONFIDENCE_AUTONOMOUS=0.85
AGENT_MIN_REVIEWS_FOR_GRADUATION=20
AGENT_MIN_REVIEWS_FOR_AUTONOMOUS=50

# Safety limits
AGENT_MAX_CAMPAIGNS_PER_RUN=5
AGENT_MAX_AUTO_APPROVALS_PER_DAY=100
AGENT_MAX_SCRAPE_FAILURE_RATE=0.5

# Notifications
AGENT_NOTIFY_EMAIL=                   # send run summary to this address
AGENT_NOTIFY_WEBHOOK=                 # POST run summary JSON to this URL
```

---

## What "Theoretically Possible" Means Here

Nothing in this design requires speculative technology:

- **Scheduling**: Railway cron jobs, already supported
- **Niche profiles**: Straightforward DB aggregates
- **Confidence scoring**: Simple Bayesian-style formula
- **LLM planner**: Claude API with structured JSON output — the existing extraction layer already does this
- **Auto-approval**: A single conditional write to `review_status`
- **Notifications**: SMTP or HTTP POST

The novel part is the feedback loop: review decisions → confidence score → graduation → reduced review burden. That loop closes naturally as the operator uses the platform normally.

---

## Related Notes

- [[pipeline]] — existing stage flow the agent orchestrates
- [[scoring-model]] — score bands the graduation logic uses
- [[2026-05-10-web-agency-campaign-goal]] — web agency mode the agent can run autonomously
