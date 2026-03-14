from __future__ import annotations
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

# Honorifics stripped when building the normalized name key for dedup
_HONORIFICS = re.compile(
    r"\b(dr\.?|mr\.?|mrs\.?|ms\.?|prof\.?|rev\.?|sir)\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^\w\s]")


def normalize_name_key(full_name: str) -> str:
    """Lowercase, strip honorifics and punctuation, normalize whitespace."""
    s = _HONORIFICS.sub("", full_name)
    s = _PUNCT.sub("", s)
    return " ".join(s.lower().split())


def split_name(full_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Conservative name split — only for validated 2-4 token names.
    - first token → first_name
    - remaining tokens joined → last_name
    full_name is the primary source of truth; this is supplemental only.
    Returns (None, None) if token count is outside [2, 4].
    """
    tokens = full_name.split()
    if not (2 <= len(tokens) <= 4):
        return None, None
    return tokens[0], " ".join(tokens[1:])


@dataclass
class RawContact:
    full_name: str
    title: Optional[str] = None
    email: Optional[str] = None   # contact-level email found near the name
    phone: Optional[str] = None   # contact-level raw phone found near the name
    source_page_type: Optional[str] = None  # PageType value string
    extraction_method: str = "deterministic"  # "deterministic" or "llm"


@dataclass
class RawEmail:
    address: str
    is_generic: bool = False
    contact_full_name: Optional[str] = None  # name this was found near (pre-link)
    source_page_type: Optional[str] = None
    extraction_method: str = "deterministic"


@dataclass
class RawPhone:
    e164: str                       # E.164 normalised
    raw: str                        # original extracted string
    contact_full_name: Optional[str] = None
    source_page_type: Optional[str] = None
    extraction_method: str = "deterministic"


@dataclass
class ExtractionResult:
    contacts: list[RawContact] = field(default_factory=list)
    emails: list[RawEmail] = field(default_factory=list)
    phones: list[RawPhone] = field(default_factory=list)
