"""Runtime config — small overrides that the operator can change via the dashboard
without restarting the server or editing .env.

Stored in ``data/leadry_config.json``.  Falls back to env / defaults when the
file does not exist or a key is missing.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_PATH = Path("data/leadry_config.json")


def _load() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not read runtime config: %s", exc)
        return {}


def _save(data: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, indent=2))


def get(key: str, default: str | None = None) -> str | None:
    """Return a runtime config value, falling back to *default*."""
    return _load().get(key, default)


def set(key: str, value: str | None) -> None:
    """Persist a runtime config value."""
    data = _load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    _save(data)


def all_settings() -> dict:
    return _load()
