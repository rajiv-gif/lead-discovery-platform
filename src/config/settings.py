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
        self.llm_api_key: str | None = os.getenv("LLM_API_KEY")
        self.llm_model: str = os.getenv("LLM_MODEL", "gpt-4o")

        self.data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
        self.pages_dir: Path = Path(os.getenv("PAGES_DIR", "data/pages"))
        self.llm_runs_dir: Path = Path(os.getenv("LLM_RUNS_DIR", "data/llm_runs"))

        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

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
