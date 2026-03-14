"""Link orphan emails and phones to contacts using page-local proximity."""
from __future__ import annotations

import re
from src.extraction.models import ExtractionResult, RawContact, RawEmail, RawPhone

_FOOTER_SIGNAL = re.compile(r"footer|site.?footer|bottom|colophon", re.IGNORECASE)

PROXIMITY_CHARS = 300


def _is_footer_email(address: str, html: str) -> bool:
    """Check if the email appears inside a footer section of the raw HTML."""
    idx = html.lower().find(address.lower())
    if idx == -1:
        return False
    surrounding = html[max(0, idx - 300):idx + 300]
    return bool(_FOOTER_SIGNAL.search(surrounding))


def link(results: list[ExtractionResult], page_htmls: dict[str, str] | None = None) -> ExtractionResult:
    """
    Merge multiple per-page ExtractionResults, then link emails/phones to contacts.

    page_htmls: optional dict of {page_type_str: raw_html} for footer detection.
    """
    merged = ExtractionResult()
    for r in results:
        merged.contacts.extend(r.contacts)
        merged.emails.extend(r.emails)
        merged.phones.extend(r.phones)

    # Footer emails → always company-level (mark as generic)
    if page_htmls:
        for em in merged.emails:
            html = page_htmls.get(em.source_page_type or "", "")
            if html and _is_footer_email(em.address, html):
                em.is_generic = True
                em.contact_full_name = None

    # Generic emails are always company-level — skip linking
    for em in merged.emails:
        if em.is_generic:
            em.contact_full_name = None

    return merged
