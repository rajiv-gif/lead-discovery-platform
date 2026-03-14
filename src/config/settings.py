from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables.

    Instantiated once at import time as ``settings``.
    Required variables raise ``RuntimeError`` if missing.
    """

    def __init__(self) -> None:
        self.database_url: str = self._require("DATABASE_URL")

        self.data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
        self.pages_dir: Path = Path(os.getenv("PAGES_DIR", "data/pages"))
        self.llm_runs_dir: Path = Path(os.getenv("LLM_RUNS_DIR", "data/llm_runs"))

        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

        # --- Google Places API ---
        # Optional at load time; runner raises RuntimeError at use time if absent.
        self.google_places_api_key: str | None = os.getenv("GOOGLE_PLACES_API_KEY")
        # Seconds to sleep between successive Places API requests (rate limiting).
        self.places_rate_limit_delay: float = float(
            os.getenv("PLACES_RATE_LIMIT_DELAY", "0.5")
        )
        # Maximum number of result pages to fetch per query (20 results/page max).
        self.places_max_pages: int = int(os.getenv("PLACES_MAX_PAGES", "3"))

        # --- Scraper ---
        # Seconds to sleep between fetches to the same domain.
        self.scraper_rate_limit_delay: float = float(
            os.getenv("SCRAPER_RATE_LIMIT_DELAY", "1.0")
        )
        # HTTP connection timeout in seconds.
        self.scraper_connect_timeout: float = float(
            os.getenv("SCRAPER_CONNECT_TIMEOUT", "10.0")
        )
        # HTTP read timeout in seconds.
        self.scraper_read_timeout: float = float(
            os.getenv("SCRAPER_READ_TIMEOUT", "30.0")
        )

        # --- Anthropic / Extraction ---
        self.anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
        self.extraction_model: str = os.getenv(
            "EXTRACTION_MODEL", "claude-3-5-haiku-20241022"
        )
        self.extraction_max_tokens: int = int(
            os.getenv("EXTRACTION_MAX_TOKENS", "1024")
        )

        # --- Export ---
        self.export_dir: str = os.getenv("EXPORT_DIR", "data/exports")

    @staticmethod
    def _require(key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {key}")
        return value

    def ensure_data_dirs(self) -> None:
        """Create data directories if they do not exist."""
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.llm_runs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
