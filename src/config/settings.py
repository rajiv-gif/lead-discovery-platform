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

        # --- Ollama (local LLM, takes priority over Anthropic if set) ---
        self.ollama_base_url: str | None = os.getenv("OLLAMA_BASE_URL")
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2")

        # --- Serper.dev (Google search, takes priority over DuckDuckGo if set) ---
        self.serper_api_key: str | None = os.getenv("SERPER_API_KEY")

        # --- Hunter.io (personal email discovery, used in enrichment stage) ---
        self.hunter_api_key: str | None = os.getenv("HUNTER_API_KEY")
        # Minimum Hunter confidence score (0–100) to store an email. 70 = usable,
        # 90 = high reliability. Lower values find more emails but with more bounces.
        self.hunter_min_confidence: int = int(os.getenv("HUNTER_MIN_CONFIDENCE", "70"))

        # --- Scraper behaviour ---
        # Set to false to ignore robots.txt and fetch all public pages.
        # robots.txt is advisory, not legally binding for publicly available data.
        self.respect_robots_txt: bool = os.getenv("RESPECT_ROBOTS_TXT", "true").lower() != "false"

        # --- Export ---
        self.export_dir: str = os.getenv("EXPORT_DIR", "data/exports")

        # --- Dashboard auth ---
        # Set all three to enable the login page. If username/password are unset,
        # the login page is shown but any credentials are accepted (dev mode only).
        # SESSION_SECRET_KEY signs the session cookie — set a long random string in prod.
        self.dashboard_username: str | None = os.getenv("DASHBOARD_USERNAME")
        self.dashboard_password: str | None = os.getenv("DASHBOARD_PASSWORD")
        self.session_secret_key: str = os.getenv(
            "SESSION_SECRET_KEY", "change-me-in-production-use-a-long-random-string"
        )

        # --- Dashboard server ---
        self.dashboard_host: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")
        # Railway injects PORT; fall back to DASHBOARD_PORT for local dev.
        self.dashboard_port: int = int(
            os.getenv("PORT") or os.getenv("DASHBOARD_PORT", "8000")
        )

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
