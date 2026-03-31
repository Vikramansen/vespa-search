from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime configuration loaded from environment variables."""

    vespa_url: str
    vespa_config_url: str

    http_timeout_s: float
    vespa_state_timeout_s: float

    search_default_limit: int
    search_min_limit: int
    search_max_limit: int


def _env(key: str, default: str) -> str:
    value = os.getenv(key, default)
    # Keep it simple: if a user provides an empty string, treat it as "use default".
    return value if value.strip() else default


settings = Settings(
    vespa_url=_env("VESPA_URL", "http://localhost:8080"),
    vespa_config_url=_env("VESPA_CONFIG_URL", "http://localhost:19071"),
    http_timeout_s=float(_env("HTTP_TIMEOUT_S", "10")),
    vespa_state_timeout_s=float(_env("VESPA_STATE_TIMEOUT_S", "3")),
    search_default_limit=int(_env("SEARCH_DEFAULT_LIMIT", "20")),
    search_min_limit=int(_env("SEARCH_MIN_LIMIT", "1")),
    search_max_limit=int(_env("SEARCH_MAX_LIMIT", "100")),
)

