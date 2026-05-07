"""Detect marketing tech signals from scraped HTML.

Reads raw HTML files from disk — no DB calls, no network requests.
Returns a TechSignals dataclass that the scorer uses as Dimension G.

Signals detected:
  google_ads      — Google Ads conversion tag (googleadservices.com / AW- ID)
  meta_pixel      — Facebook/Meta Pixel (fbq / connect.facebook.net)
  google_analytics — GA4 or Universal Analytics (gtag / analytics.js)
  tiktok_pixel    — TikTok Pixel (analytics.tiktok.com / ttq)
  cms             — CMS/platform: shopify | wordpress | webflow | wix |
                    squarespace | woocommerce | unknown
  has_chat        — Live chat widget (Intercom, Drift, Crisp, Tawk, Tidio, …)
  has_cookie_banner — GDPR cookie consent tool (CookieBot, OneTrust, Axeptio, …)
  has_blog        — Blog / news section linked from the page
  has_faq         — FAQ page or FAQPage schema present

Interpretation guide for agency sales:
  google_ads=False + meta_pixel=False  → not running paid ads (pitch opportunity)
  google_analytics=False               → flying blind on traffic data
  has_chat=False                       → no real-time visitor engagement
  cms="wix" | "squarespace"           → often a rebuild conversation starter
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TechSignals:
    google_ads: bool = False
    meta_pixel: bool = False
    google_analytics: bool = False
    tiktok_pixel: bool = False
    cms: Optional[str] = None          # e.g. "shopify", "wordpress", None
    has_chat: bool = False
    has_cookie_banner: bool = False
    has_blog: bool = False
    has_faq: bool = False

    def as_dict(self) -> dict:
        return {
            "google_ads": self.google_ads,
            "meta_pixel": self.meta_pixel,
            "google_analytics": self.google_analytics,
            "tiktok_pixel": self.tiktok_pixel,
            "cms": self.cms,
            "has_chat": self.has_chat,
            "has_cookie_banner": self.has_cookie_banner,
            "has_blog": self.has_blog,
            "has_faq": self.has_faq,
        }

    @property
    def running_paid_ads(self) -> bool:
        return self.google_ads or self.meta_pixel or self.tiktok_pixel

    @property
    def missing_analytics(self) -> bool:
        return not self.google_analytics

    @property
    def ad_gap_count(self) -> int:
        """Number of major ad platforms the company is NOT using (0–3)."""
        return sum([
            not self.google_ads,
            not self.meta_pixel,
            not self.tiktok_pixel,
        ])


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Google Ads: conversion tag or remarketing
_GOOGLE_ADS_RE = re.compile(
    r"googleadservices\.com|googleads\.g\.doubleclick\.net"
    r"|[\"']AW-\d{9,}[\"']"
    r"|google_conversion_id",
    re.IGNORECASE,
)

# Meta / Facebook Pixel
_META_PIXEL_RE = re.compile(
    r"connect\.facebook\.net[^\s\"']*fbevents\.js"
    r"|fbq\s*\("
    r"|facebook\.com/tr\b",
    re.IGNORECASE,
)

# Google Analytics (GA4 or Universal Analytics)
_GA_RE = re.compile(
    r"google-analytics\.com/analytics\.js"
    r"|google-analytics\.com/ga\.js"
    r"|googletagmanager\.com/gtag/js"
    r"|gtag\s*\(\s*[\"']config[\"']\s*,\s*[\"'](?:G-|UA-)",
    re.IGNORECASE,
)

# TikTok Pixel
_TIKTOK_RE = re.compile(
    r"analytics\.tiktok\.com|tiktok\.com/i18n/pixel"
    r"|ttq\s*\.\s*(?:load|track)\s*\(",
    re.IGNORECASE,
)

# CMS fingerprints — ordered so more specific patterns win
_CMS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("shopify",      re.compile(r"cdn\.shopify\.com|Shopify\.theme|shopify\.com/s/files", re.IGNORECASE)),
    ("woocommerce",  re.compile(r"woocommerce|wp-content/plugins/woocommerce", re.IGNORECASE)),
    ("wordpress",    re.compile(r"wp-content/|wp-json/|wp-includes/", re.IGNORECASE)),
    ("webflow",      re.compile(r"webflow\.com/css|\.webflow\.com|data-wf-page", re.IGNORECASE)),
    ("squarespace",  re.compile(r"squarespace\.com|static\.squarespace", re.IGNORECASE)),
    ("wix",          re.compile(r"wix\.com/|static\.parastorage\.com|wixstatic\.com", re.IGNORECASE)),
]

# Live chat widgets
_CHAT_RE = re.compile(
    r"intercomcdn\.com|intercom\.io/js"
    r"|js\.driftt\.com|drift\.com/include"
    r"|crisp\.chat|client\.crisp\.chat"
    r"|tawk\.to/s1/"
    r"|tidio\.com/code/"
    r"|livechat\.com/tracking"
    r"|zopim\.com|zendesk\.com/embeddable",
    re.IGNORECASE,
)

# Cookie consent / GDPR banners
_COOKIE_RE = re.compile(
    r"cookiebot\.com|cookieconsent"
    r"|onetrust\.com|optanon"
    r"|cookiepro\.com"
    r"|axeptio\.eu"
    r"|tarteaucitron"
    r"|gdpr-cookie",
    re.IGNORECASE,
)

# Blog / news section in links
_BLOG_RE = re.compile(
    r"href=[\"'][^\"']*(?:/blog|/news|/articles?|/posts?|/insights|/resources)[/\"']",
    re.IGNORECASE,
)

# FAQ — link or FAQPage schema
_FAQ_RE = re.compile(
    r"href=[\"'][^\"']*(?:/faq|/faqs|/frequently-asked)[/\"']"
    r"|\"@type\"\s*:\s*\"FAQPage\""
    r"|<h[1-6][^>]*>\s*(?:FAQ|Frequently Asked)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def detect_tech_signals(pages: list, base_path: Path = Path(".")) -> TechSignals:
    """Read HTML files for *pages* and return detected marketing tech signals.

    Scans all pages for a company and aggregates signals across all of them
    (e.g. the Meta Pixel might be on the homepage only).  Stops early once
    every signal has been found.
    """
    signals = TechSignals()
    found_cms = False

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

        if not signals.google_ads and _GOOGLE_ADS_RE.search(html):
            signals.google_ads = True

        if not signals.meta_pixel and _META_PIXEL_RE.search(html):
            signals.meta_pixel = True

        if not signals.google_analytics and _GA_RE.search(html):
            signals.google_analytics = True

        if not signals.tiktok_pixel and _TIKTOK_RE.search(html):
            signals.tiktok_pixel = True

        if not found_cms:
            for cms_name, pattern in _CMS_PATTERNS:
                if pattern.search(html):
                    signals.cms = cms_name
                    found_cms = True
                    break

        if not signals.has_chat and _CHAT_RE.search(html):
            signals.has_chat = True

        if not signals.has_cookie_banner and _COOKIE_RE.search(html):
            signals.has_cookie_banner = True

        if not signals.has_blog and _BLOG_RE.search(html):
            signals.has_blog = True

        if not signals.has_faq and _FAQ_RE.search(html):
            signals.has_faq = True

        # Early exit once all boolean signals confirmed
        if all([
            signals.google_ads,
            signals.meta_pixel,
            signals.google_analytics,
            signals.tiktok_pixel,
            found_cms,
            signals.has_chat,
            signals.has_cookie_banner,
            signals.has_blog,
            signals.has_faq,
        ]):
            break

    return signals
