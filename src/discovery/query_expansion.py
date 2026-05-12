"""LLM-powered query expansion for web-search campaigns.

Given a single user query (e.g. "luxury fashion Shopify stores"), generates
several semantically distinct alternatives that broaden search coverage.

Uses the shared LLM client factory — Ollama (local) takes priority over
Anthropic if OLLAMA_BASE_URL is set, so your local model is used by default.
Falls back gracefully to an empty list if no LLM is configured or the call
fails, so campaign creation always succeeds.
"""
from __future__ import annotations

import json
import logging

from src.config.settings import settings
from src.extraction.llm import LLMClient, get_llm_client

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a search query specialist helping a lead generation researcher "
    "find more results by broadening their search terms."
)

_PROMPT_TEMPLATE = """\
Original query: "{query}"
Campaign goal: {goal}

Generate {n} alternative Google search queries that would find similar \
businesses using different phrasings. Rules:
- Each must be a short, valid Google search query (no prose)
- Vary vocabulary: synonyms, subcategories, brand-adjacent terms
- Do NOT repeat the original query verbatim
- Return ONLY a JSON array of strings, nothing else

Example output: ["premium fashion online store", "luxury clothing boutique site"]"""


def expand_queries(
    query: str,
    campaign_goal: str = "lead_gen",
    n: int = 7,
    client: LLMClient | None = None,
) -> list[str]:
    """Return up to *n* alternative search queries for *query*.

    Args:
        query: The original user-supplied search query.
        campaign_goal: Used as context for the LLM (e.g. "shopify", "lead_gen").
        n: Maximum number of alternatives to return (not counting the original).
        client: Optional pre-built LLM client; uses settings-based factory if None.

    Returns:
        List of alternative query strings (may be empty if LLM unavailable or fails).
    """
    if client is None:
        client = get_llm_client(
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            anthropic_api_key=settings.anthropic_api_key,
            anthropic_model=settings.extraction_model,
        )

    if client is None:
        log.debug("No LLM client available — skipping query expansion")
        return []

    prompt = _PROMPT_TEMPLATE.format(query=query, goal=campaign_goal, n=n)

    try:
        raw = client.complete(system=_SYSTEM, user=prompt, max_tokens=512)
        raw = raw.strip()

        # Strip markdown fences that some models add
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")]
        raw = raw.strip()

        candidates = json.loads(raw)
        if not isinstance(candidates, list):
            raise ValueError(f"Expected list, got {type(candidates).__name__}")

        result = [
            q.strip() for q in candidates
            if isinstance(q, str) and q.strip() and q.strip().lower() != query.strip().lower()
        ]
        log.info("Query expansion: %d alternatives for %r", len(result), query)
        return result[:n]

    except Exception as exc:
        log.warning("Query expansion failed (%s) — returning empty list", exc)
        return []
