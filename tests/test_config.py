from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from umamusume_qq_bot.config import load_settings


class SettingsTests(unittest.TestCase):
    def test_loads_agent_api_access_key(self):
        env = {
            "AppID": "app-id",
            "AppSecret": "app-secret",
            "UMAMUSEME_AGENT_API_ACCESS_KEY": "API_ACCESS_KEY##test",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings(env_file="/nonexistent/test.env")

        self.assertEqual(settings.agent_api_access_key, "API_ACCESS_KEY##test")
        self.assertEqual(settings.agent_timeout_seconds, 600)

    def test_supports_correctly_spelled_alias(self):
        env = {
            "AppID": "app-id",
            "AppSecret": "app-secret",
            "UMAMUSUME_AGENT_API_ACCESS_KEY": "correctly-spelled-key",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings(env_file="/nonexistent/test.env")

        self.assertEqual(settings.agent_api_access_key, "correctly-spelled-key")


if __name__ == "__main__":
    unittest.main()
