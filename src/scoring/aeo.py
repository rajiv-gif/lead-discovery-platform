"""Detect AEO (Answer Engine Optimisation) signals from scraped HTML.

Reads raw HTML files from disk — no DB calls, no network requests.
Returns an AeoSignals dataclass that the scorer uses as Dimension F.

Signals checked:
  has_json_ld              — any <script type="application/ld+json"> block present
  has_local_business_schema — JSON-LD contains a LocalBusiness / Dentist / similar type
  has_viewport_meta        — <meta name="viewport"> present (mobile-friendly)
  has_og_tags              — Open Graph <meta property="og:*"> present
  is_https                 — homepage URL starts with https://
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AeoSignals:
    has_json_ld: bool = False
    has_local_business_schema: bool = False
    has_viewport_meta: bool = False
    has_og_tags: bool = False
    is_https: bool = False


_LD_JSON_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)
_VIEWPORT_RE = re.compile(r"<meta[^>]+name=[\"']viewport[\"']", re.IGNORECASE)
_OG_RE = re.compile(r"<meta[^>]+property=[\"']og:", re.IGNORECASE)

# @type values that count as a LocalBusiness schema
_LOCAL_TYPES = frozenset(
    {
        "LocalBusiness",
        "Dentist",
        "Physician",
        "MedicalBusiness",
        "HealthAndBeautyBusiness",
        "HomeAndConstructionBusiness",
        "FoodEstablishment",
        "Store",
        "ProfessionalService",
        "MedicalClinic",
        "Optician",
        "Optometrist",
    }
)


def detect_aeo_signals(pages: list, base_path: Path = Path(".")) -> AeoSignals:
    """Read HTML files for *pages* and return detected AEO signals.

    Scans all pages for a company so that JSON-LD on an inner page is still
    detected.  Stops early once all signals are confirmed present (fast path
    for well-optimised sites).
    """
    signals = AeoSignals()

    for page in pages:
        if not page.raw_html_path:
            continue
        html_path = base_path / page.raw_html_path
        if not html_path.is_file():
            continue
        try:
            html = html_path.read_text(errors="ignore")
        except OSError:
            continue

        # HTTPS — use the stored URL, not the on-disk path
        url: str = getattr(page, "url", "") or ""
        if url.startswith("https://"):
            signals.is_https = True

        if _VIEWPORT_RE.search(html):
            signals.has_viewport_meta = True

        if _OG_RE.search(html):
            signals.has_og_tags = True

        for match in _LD_JSON_RE.finditer(html):
            signals.has_json_ld = True
            try:
                data = json.loads(match.group(1))
            except (json.JSONDecodeError, ValueError):
                continue
            # Flatten: handles bare object, list, or @graph wrapper
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                # @graph is a list of typed nodes
                for n in node.get("@graph", [node]):
                    if not isinstance(n, dict):
                        continue
                    raw_type = n.get("@type", "")
                    types = raw_type if isinstance(raw_type, list) else [raw_type]
                    if any(t in _LOCAL_TYPES for t in types):
                        signals.has_local_business_schema = True

        # Early exit once all positive signals found
        if all(
            [
                signals.has_json_ld,
                signals.has_local_business_schema,
                signals.has_viewport_meta,
                signals.has_og_tags,
                signals.is_https,
            ]
        ):
            break

    return signals
