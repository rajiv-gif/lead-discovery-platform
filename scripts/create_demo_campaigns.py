"""Create demo campaigns for screenshots/videos.

Run from the project root:
    python scripts/create_demo_campaigns.py

Skips campaigns that already exist by name (idempotent).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.db.session import get_session
from src.models.campaign import Campaign
from src.models.enums import CampaignStatus, DiscoverySource

CAMPAIGNS = [
    {
        "name": "Shopify DTC Brands — Western Europe",
        "niche": "shopify stores",
        "discovery_source": DiscoverySource.WEB_SEARCH,
        "ecommerce_platform": "shopify",
        "search_queries": [
            "shopify store fashion Netherlands",
            "shopify store homeware Germany",
            "shopify store beauty France",
        ],
    },
    {
        "name": "B2B SaaS Founders — San Francisco",
        "niche": "B2B SaaS",
        "discovery_source": DiscoverySource.WEB_SEARCH,
        "search_queries": [
            "B2B SaaS startup San Francisco",
            "enterprise software startup Bay Area",
        ],
    },
    {
        "name": "AI Startups — New York",
        "niche": "AI startups",
        "discovery_source": DiscoverySource.WEB_SEARCH,
        "search_queries": [
            "AI startup New York",
            "machine learning company NYC",
        ],
    },
    {
        "name": "Outbound Sales Agencies — London",
        "niche": "outbound sales agencies",
        "discovery_source": DiscoverySource.WEB_SEARCH,
        "search_queries": [
            "outbound sales agency London",
            "B2B lead generation agency London",
        ],
    },
]


def main() -> None:
    with get_session() as session:
        for data in CAMPAIGNS:
            existing = session.query(Campaign).filter_by(name=data["name"]).first()
            if existing:
                print(f"  skip  {data['name']!r} (already exists, id={existing.id})")
                continue

            campaign = Campaign(
                name=data["name"],
                niche=data.get("niche", ""),
                status=CampaignStatus.DRAFT,
                discovery_source=data["discovery_source"],
                search_queries=data.get("search_queries"),
                ecommerce_platform=data.get("ecommerce_platform"),
            )
            session.add(campaign)
            session.flush()
            print(f"created {data['name']!r} (id={campaign.id})")

        session.commit()
    print("\nDone.")


if __name__ == "__main__":
    main()
