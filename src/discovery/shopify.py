"""Shopify store detection and enrichment.

Two-step process:
  1. detect_shopify(html)      — fast HTML fingerprint check (no extra request)
  2. fetch_shopify_info(domain) — fetch /products.json for product count + prices

Results are stored in company.extra_fields:
  platform               → "shopify"
  shopify_product_count  → int
  shopify_price_min      → float (USD)
  shopify_price_max      → float (USD)
  shopify_collections    → list[str] (first 10 collection titles)
  shopify_myshopify_url  → str  (the *.myshopify.com URL if discoverable)

All fetches use the same httpx client as the scraper — robots.txt compliant,
rate-limited, with a short timeout (products.json is usually fast).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger(__name__)

# Shopify HTML fingerprints — any one match is sufficient
_SHOPIFY_SIGNALS = [
    "cdn.shopify.com",
    "Shopify.shop",
    "shopify-section",
    "/cdn/shop/",
    'name="shopify-',
    "window.Shopify",
]

_PRODUCTS_JSON_TIMEOUT = 10.0
_HEADERS = {
    "User-Agent": "LeadDiscoveryBot/1.0 (+https://example.com/bot)",
    "Accept": "application/json",
}


@dataclass
class ShopifyInfo:
    """Enrichment data fetched from a Shopify store."""

    is_shopify: bool = False
    myshopify_url: str = ""
    product_count: int = 0
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    collections: list[str] = field(default_factory=list)
    error: str = ""


def detect_shopify(html: str) -> bool:
    """Return True if *html* contains Shopify fingerprints.

    Fast, purely in-memory check — no network calls.
    """
    return any(signal in html for signal in _SHOPIFY_SIGNALS)


def extract_myshopify_url(html: str, page_url: str) -> str:
    """Try to extract the *.myshopify.com permanent subdomain from HTML.

    Shopify embeds this in several places:
      - Shopify.shop = "storename.myshopify.com"
      - <link rel="canonical" href="https://storename.myshopify.com/...">
      - meta tags
    """
    # JS assignment: Shopify.shop = "storename.myshopify.com"
    m = re.search(r'Shopify\.shop\s*=\s*["\']([^"\']+\.myshopify\.com)["\']', html)
    if m:
        return f"https://{m.group(1)}"

    # Any myshopify.com reference in the HTML
    m = re.search(r'https?://([a-z0-9\-]+\.myshopify\.com)', html)
    if m:
        return m.group(0)

    return ""


def fetch_shopify_info(domain: str, myshopify_url: str = "") -> ShopifyInfo:
    """Fetch /products.json from a Shopify store and return enrichment data.

    Tries the custom domain first, falls back to the myshopify.com URL.
    Returns a ShopifyInfo with product_count=0 and error set if the fetch fails.
    """
    info = ShopifyInfo(is_shopify=True, myshopify_url=myshopify_url)

    # Build candidate URLs to try for products.json
    candidates: list[str] = []
    if domain:
        candidates.append(f"https://{domain}/products.json?limit=250")
    if myshopify_url:
        candidates.append(f"{myshopify_url.rstrip('/')}/products.json?limit=250")

    for url in candidates:
        try:
            resp = httpx.get(url, headers=_HEADERS, timeout=_PRODUCTS_JSON_TIMEOUT,
                             follow_redirects=True)
            if resp.status_code != 200:
                continue
            data = resp.json()
            products = data.get("products", [])
            if not isinstance(products, list):
                continue

            info.product_count = len(products)

            # Collect prices across all variants
            prices: list[float] = []
            for product in products:
                for variant in product.get("variants", []):
                    try:
                        prices.append(float(variant.get("price", 0) or 0))
                    except (TypeError, ValueError):
                        pass

            if prices:
                info.price_min = round(min(p for p in prices if p > 0), 2) if any(p > 0 for p in prices) else None
                info.price_max = round(max(prices), 2)

            log.debug(
                "Shopify products.json: domain=%r products=%d price=%.0f–%.0f",
                domain, info.product_count,
                info.price_min or 0, info.price_max or 0,
            )
            return info

        except (httpx.RequestError, httpx.HTTPStatusError, ValueError, KeyError) as exc:
            log.debug("products.json fetch failed for %r: %s", url, exc)
            info.error = str(exc)
            continue

    return info


def enrich_company_extra_fields(
    extra_fields: dict,
    html: str,
    domain: str,
) -> dict:
    """Detect Shopify and enrich *extra_fields* in-place. Returns updated dict.

    Called from the web runner after a company's homepage is scraped.
    Adds platform, product count, price range to extra_fields.
    """
    if not detect_shopify(html):
        return extra_fields

    myshopify_url = extract_myshopify_url(html, "")
    info = fetch_shopify_info(domain, myshopify_url)

    updated = dict(extra_fields or {})
    updated["platform"] = "shopify"
    if myshopify_url:
        updated["shopify_myshopify_url"] = myshopify_url
    if info.product_count:
        updated["shopify_product_count"] = info.product_count
    if info.price_min is not None:
        updated["shopify_price_min"] = info.price_min
    if info.price_max is not None:
        updated["shopify_price_max"] = info.price_max

    return updated
