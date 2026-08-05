from __future__ import annotations

import json
import unittest
from typing import Any

from umamusume_qq_bot.agent_client import AgentClient, AgentError


class _FakeResponse:
    def __init__(self, payload: Any, status: int = 200):
        self.status = status
        self._body = json.dumps(payload, ensure_ascii=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def text(self) -> str:
        return self._body


class _FakeSession:
    def __init__(self, payload: Any):
        self.closed = False
        self.payload = payload
        self.requests: list[dict[str, Any]] = []

    def request(self, **kwargs):
        self.requests.append(kwargs)
        return _FakeResponse(self.payload)

    async def close(self) -> None:
        self.closed = True


class AgentClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_access_key_is_sent_to_agent(self):
        client = AgentClient(
            base_url="http://agent.example",
            timeout_seconds=5,
            api_access_key="  test-access-key  ",
        )
        session = _FakeSession({"characters": ["爱慕织姬"]})
        client._session = session

        characters = await client.list_characters()

        self.assertEqual(characters, ["爱慕织姬"])
        self.assertEqual(
            session.requests[0]["headers"],
            {"X-API-Key": "test-access-key"},
        )

    async def test_empty_api_access_key_does_not_send_auth_header(self):
        client = AgentClient(
            base_url="http://agent.example",
            timeout_seconds=5,
        )
        session = _FakeSession({"characters": []})
        client._session = session

        await client.list_characters()

        self.assertIsNone(session.requests[0]["headers"])

    async def test_chat_sends_dialogue_event_fields(self):
        client = AgentClient(
            base_url="http://agent.example",
            timeout_seconds=5,
            api_access_key="test-access-key",
        )
        session = _FakeSession({"action": "点头", "dialogue": "知道了。"})
        client._session = session

        reply = await client.chat(
            "session-1",
            "下雨了",
            dialogue_event={
                "speaker": {"actor_id": "narrator"},
                "event_type": "scene_event",
                "context_events": [{"content": "夜幕降临"}],
            },
        )

        payload = session.requests[0]["json"]
        self.assertEqual(reply, "动作：点头\n对白：知道了。")
        self.assertEqual(payload["event_type"], "scene_event")
        self.assertEqual(payload["context_events"], [{"content": "夜幕降临"}])
        self.assertFalse(payload["generate_voice"])

    async def test_create_director_session_uses_frontend_protocol(self):
        client = AgentClient(base_url="http://agent.example", timeout_seconds=5)
        session = _FakeSession({"session_id": "director-1", "events": []})
        client._session = session

        result = await client.create_director_session(
            character_names=["爱慕织姬", "无声铃鹿"],
            user_uuid="user-1",
            template_id="city_park_afternoon",
            story_outline="训练后偶遇",
        )

        self.assertEqual(result["session_id"], "director-1")
        payload = session.requests[0]["json"]
        self.assertEqual(payload["template_id"], "city_park_afternoon")
        self.assertEqual(payload["character_names"], ["爱慕织姬", "无声铃鹿"])
        self.assertEqual(payload["story_outline"], "训练后偶遇")

    def test_extracts_json_reply_v2(self):
        reply = AgentClient._extract_reply(
            {
                "action": "爱慕织姬轻轻点头。",
                "dialogue": "训练员，我们开始吧。",
                "message": {
                    "role": "assistant",
                    "content": "训练员，我们开始吧。",
                },
            }
        )

        self.assertEqual(
            reply,
            "动作：爱慕织姬轻轻点头。\n对白：训练员，我们开始吧。",
        )

    def test_extracts_nested_structured_reply(self):
        reply = AgentClient._extract_reply(
            {
                "message": {
                    "role": "assistant",
                    "action": "无",
                    "dialogue": "晚上好。",
                }
            }
        )

        self.assertEqual(reply, "动作：无\n对白：晚上好。")

    def test_keeps_legacy_reply_compatible(self):
        reply = AgentClient._extract_reply({"reply": "动作：挥手\n对白：你好"})

        self.assertEqual(reply, "动作：挥手\n对白：你好")

    def test_rejects_response_without_reply_text(self):
        with self.assertRaisesRegex(AgentError, "missing reply text"):
            AgentClient._extract_reply({"voice": {"state": "queued"}})


if __name__ == "__main__":
    unittest.main()
