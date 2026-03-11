from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_id: str
    app_secret: str
    agent_base_url: str
    log_level: str
    agent_timeout_seconds: float
    characters_cache_ttl_seconds: int


def load_settings(env_file: str | Path = ".env") -> Settings:
    load_dotenv(dotenv_path=env_file, override=False)

    app_id = os.getenv("AppID", "").strip()
    app_secret = os.getenv("AppSecret", "").strip()
    if not app_id:
        raise RuntimeError("Missing required env var: AppID")
    if not app_secret:
        raise RuntimeError("Missing required env var: AppSecret")

    return Settings(
        app_id=app_id,
        app_secret=app_secret,
        agent_base_url=os.getenv("AGENT_BASE_URL", "http://127.0.0.1:1111").strip().rstrip("/"),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        agent_timeout_seconds=float(os.getenv("AGENT_TIMEOUT_SECONDS", "20")),
        characters_cache_ttl_seconds=int(os.getenv("CHARACTERS_CACHE_TTL_SECONDS", "300")),
    )
