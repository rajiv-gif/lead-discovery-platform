"""Dedup deterministic and LLM ExtractionResults."""
from __future__ import annotations

from typing import Optional

from src.extraction.models import ExtractionResult, RawContact, RawEmail, RawPhone, normalize_name_key


def merge(det: ExtractionResult, llm: Optional[ExtractionResult]) -> ExtractionResult:
    result = ExtractionResult()

    # Merge contacts by normalized_name_key
    seen_names: set[str] = set()
    for c in det.contacts + (llm.contacts if llm else []):
        key = normalize_name_key(c.full_name)
        if key and key not in seen_names:
            seen_names.add(key)
            result.contacts.append(c)

    # Merge emails by lowercased address
    seen_emails: set[str] = set()
    for em in det.emails + (llm.emails if llm else []):
        key = em.address.lower()
        if key not in seen_emails:
            seen_emails.add(key)
            result.emails.append(em)

    # Merge phones by E.164 number
    seen_phones: set[str] = set()
    for ph in det.phones + (llm.phones if llm else []):
        key = ph.e164
        if key not in seen_phones:
            seen_phones.add(key)
            result.phones.append(ph)

    return result
