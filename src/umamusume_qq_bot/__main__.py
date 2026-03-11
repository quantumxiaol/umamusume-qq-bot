from __future__ import annotations

import logging

from .agent_client import AgentClient
from .bot_client import UmamusumeBotClient
from .config import load_settings
from .logging_setup import setup_logging
from .state_store import ConversationStore


def main() -> None:
    settings = load_settings()
    log_file = setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting QQ bot, logs=%s agent_base_url=%s", log_file, settings.agent_base_url)

    client = UmamusumeBotClient(
        settings=settings,
        agent_client=AgentClient(
            base_url=settings.agent_base_url,
            timeout_seconds=settings.agent_timeout_seconds,
            characters_cache_ttl_seconds=settings.characters_cache_ttl_seconds,
        ),
        state_store=ConversationStore(),
    )
    client.run(appid=settings.app_id, secret=settings.app_secret)


if __name__ == "__main__":
    main()
