"""Root conftest — set required env vars before any module is imported.

settings = Settings() runs at module level in src/config/settings.py, so
DATABASE_URL must exist in the environment before pytest collects any test
that transitively imports settings.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test_db")
os.environ.setdefault("GOOGLE_PLACES_API_KEY", "test-placeholder-key")
