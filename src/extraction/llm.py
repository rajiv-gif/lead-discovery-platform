"""LLM-based extraction — supports Anthropic and Ollama (OpenAI-compatible)."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional, Protocol

import anthropic
import httpx

from src.extraction.models import ExtractionResult, RawContact, RawEmail, RawPhone
from src.models.company_page import CompanyPage

log = logging.getLogger(__name__)

# ---- LLMClient protocol (swap provider without touching runner) ----


class LLMClient(Protocol):
    def complete(self, system: str, user: str, max_tokens: int) -> str: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text


class OllamaClient:
    """OpenAI-compatible client for a local Ollama server."""

    def __init__(self, base_url: str, model: str, timeout: float = 240.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = httpx.post(
            f"{self._base_url}/v1/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ---- Prompt ----

_SYSTEM_PROMPT = """You are an information extraction assistant.
Extract contact information from the provided web page text.
Return ONLY valid JSON matching this exact schema — no prose, no markdown:
{
  "contacts": [
    {"full_name": "string or null", "title": "string or null", "email": "string or null", "phone": "string or null"}
  ],
  "company_emails": ["string", ...],
  "company_phones": ["string", ...]
}
Rules:
- contacts: individual named people found on the page. Include their direct email/phone if clearly associated.
- company_emails: generic practice/office email addresses (e.g. info@, contact@).
- company_phones: main practice phone numbers not tied to a specific person.
- Use null for missing individual fields.
- Return empty arrays if nothing found.
- Do not invent data."""


def build_user_prompt(page_text: str, company_name: str) -> str:
    return f"Company: {company_name}\n\nPage text:\n{page_text[:8000]}"


# ---- Schema parse ----


def _strip_fences(raw: str) -> str:
    """Strip markdown code fences that some models wrap JSON in."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]  # drop opening ```json line
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
    return raw.strip()


def _parse_response(raw: str, method: str = "llm") -> ExtractionResult:
    data = json.loads(_strip_fences(raw))  # raises json.JSONDecodeError if invalid
    result = ExtractionResult()

    for c in data.get("contacts", []) or []:
        if not isinstance(c, dict):
            continue
        name = c.get("full_name") or None
        if not name:
            continue
        result.contacts.append(RawContact(
            full_name=name,
            title=c.get("title") or None,
            email=c.get("email") or None,
            phone=c.get("phone") or None,
            extraction_method=method,
        ))

    for addr in data.get("company_emails", []) or []:
        if addr and isinstance(addr, str):
            result.emails.append(RawEmail(
                address=addr.lower().strip(),
                is_generic=True,
                extraction_method=method,
            ))

    for ph in data.get("company_phones", []) or []:
        if ph and isinstance(ph, str):
            result.phones.append(RawPhone(
                e164=ph.strip(),   # linker/persist will re-normalise
                raw=ph.strip(),
                extraction_method=method,
            ))

    return result


# ---- Client factory ----


def get_llm_client(
    ollama_base_url: str | None = None,
    ollama_model: str = "llama3.2",
    anthropic_api_key: str | None = None,
    anthropic_model: str = "claude-haiku-4-5",
) -> Optional[LLMClient]:
    """Return the best available LLM client.

    Priority: Ollama (local) → Anthropic API → None.

    Pass settings values directly; the caller decides where config comes from
    so this function stays testable without env vars.
    """
    if ollama_base_url:
        return OllamaClient(base_url=ollama_base_url, model=ollama_model)
    if anthropic_api_key:
        return AnthropicClient(api_key=anthropic_api_key, model=anthropic_model)
    return None


# ---- Entry point ----


def call_llm(
    client: LLMClient,
    page: CompanyPage,
    company_name: str,
    llm_runs_dir: Path,
    max_tokens: int = 1024,
    max_retries: int = 2,
) -> Optional[ExtractionResult]:
    """Call the LLM and parse the result, retrying on malformed JSON.

    JSON parse failures are retried up to *max_retries* times — local models
    like gemma4 are non-deterministic and often self-correct on a second attempt.
    Network/timeout errors are not retried (they're unlikely to self-resolve).
    """
    run_id = str(uuid.uuid4())
    artifact_path = llm_runs_dir / f"{run_id}.json"
    user_prompt = build_user_prompt(page.extracted_text or "", company_name)

    raw_response: Optional[str] = None
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_retries + 2):   # +2 → initial attempt + max_retries retries
        try:
            raw_response = client.complete(
                system=_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=max_tokens,
            )
            result = _parse_response(raw_response)
            _write_artifact(artifact_path, run_id, page, user_prompt, raw_response, status="ok")
            if attempt > 1:
                log.debug("LLM run %s: succeeded on attempt %d", run_id, attempt)
            return result
        except json.JSONDecodeError as exc:
            last_exc = exc
            if attempt <= max_retries:
                log.debug("LLM run %s: malformed JSON (attempt %d/%d) — retrying",
                          run_id, attempt, max_retries + 1)
                continue
            log.warning("LLM run %s: malformed JSON after %d attempts — %s", run_id, attempt, exc)
            _write_artifact(artifact_path, run_id, page, user_prompt, raw_response,
                            status="malformed", error=str(exc))
            return None
        except Exception as exc:
            # Network errors, timeouts — don't retry, they're unlikely to self-resolve
            log.warning("LLM run %s: API/parse error — %s", run_id, exc)
            _write_artifact(artifact_path, run_id, page, user_prompt, raw_response,
                            status="error", error=str(exc))
            return None

    return None  # unreachable, but satisfies type checker


def _write_artifact(
    path: Path,
    run_id: str,
    page: CompanyPage,
    prompt: str,
    response: Optional[str],
    status: str,
    error: Optional[str] = None,
) -> None:
    artifact = {
        "run_id": run_id,
        "company_id": str(page.company_id),
        "page_id": str(page.id),
        "page_type": page.page_type.value if page.page_type else None,
        "status": status,
        "prompt": prompt,
        "response": response,
    }
    if error:
        artifact["error"] = error
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))
    except OSError as exc:
        log.warning("Could not write LLM artifact %s: %s", path, exc)
