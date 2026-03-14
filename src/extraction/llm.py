"""LLM-based extraction using Anthropic claude-3-5-haiku."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional, Protocol

import anthropic

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


def _parse_response(raw: str, method: str = "llm") -> ExtractionResult:
    data = json.loads(raw)  # raises json.JSONDecodeError if invalid
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


# ---- Entry point ----


def call_llm(
    client: LLMClient,
    page: CompanyPage,
    company_name: str,
    llm_runs_dir: Path,
    max_tokens: int = 1024,
) -> Optional[ExtractionResult]:
    run_id = str(uuid.uuid4())
    artifact_path = llm_runs_dir / f"{run_id}.json"
    user_prompt = build_user_prompt(page.extracted_text or "", company_name)

    raw_response: Optional[str] = None
    try:
        raw_response = client.complete(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=max_tokens,
        )
        result = _parse_response(raw_response)
        _write_artifact(artifact_path, run_id, page, user_prompt, raw_response, status="ok")
        return result
    except json.JSONDecodeError as exc:
        log.warning("LLM run %s: malformed JSON — %s", run_id, exc)
        _write_artifact(artifact_path, run_id, page, user_prompt, raw_response, status="malformed", error=str(exc))
        return None
    except Exception as exc:
        log.warning("LLM run %s: API/parse error — %s", run_id, exc)
        _write_artifact(artifact_path, run_id, page, user_prompt, raw_response, status="error", error=str(exc))
        return None


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
