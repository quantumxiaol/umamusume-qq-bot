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
    agent_api_access_key: str = ""
    database_path: str = "data/bot.sqlite3"
    local_history_max_messages: int = 1000


def load_settings(env_file: str | Path = ".env") -> Settings:
    load_dotenv(dotenv_path=env_file, override=False)

    app_id = os.getenv("AppID", "").strip()
    app_secret = os.getenv("AppSecret", "").strip()
    if not app_id:
        raise RuntimeError("Missing required env var: AppID")
    if not app_secret:
        raise RuntimeError("Missing required env var: AppSecret")

    agent_base_url = (
        os.getenv("UMAMUSEME_AGENT_URL", "").strip()
        or os.getenv("UMAMUSUME_AGENT_URL", "").strip()
        or os.getenv("AGENT_BASE_URL", "").strip()
        or "http://127.0.0.1:1111"
    )
    agent_api_access_key = (
        os.getenv("UMAMUSEME_AGENT_API_ACCESS_KEY", "").strip()
        or os.getenv("UMAMUSUME_AGENT_API_ACCESS_KEY", "").strip()
        or os.getenv("AGENT_API_ACCESS_KEY", "").strip()
    )

    return Settings(
        app_id=app_id,
        app_secret=app_secret,
        agent_base_url=agent_base_url.rstrip("/"),
        agent_api_access_key=agent_api_access_key,
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        agent_timeout_seconds=float(os.getenv("AGENT_TIMEOUT_SECONDS", "600")),
        characters_cache_ttl_seconds=int(os.getenv("CHARACTERS_CACHE_TTL_SECONDS", "300")),
        database_path=os.getenv("BOT_DATABASE_PATH", "data/bot.sqlite3").strip()
        or "data/bot.sqlite3",
        local_history_max_messages=max(
            0,
            int(os.getenv("LOCAL_HISTORY_MAX_MESSAGES", "1000")),
        ),
    )
