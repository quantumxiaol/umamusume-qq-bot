from __future__ import annotations

import unittest
from typing import Any

from umamusume_qq_bot.bot_client import UmamusumeBotClient
from umamusume_qq_bot.state_store import ConversationStore


class _FakeAgent:
    def __init__(self):
        self.chat_calls: list[dict[str, Any]] = []
        self.director_turn_calls: list[dict[str, Any]] = []
        self.import_calls: list[dict[str, Any]] = []
        self.history_messages: list[dict[str, Any]] = []

    async def get_status(self):
        return {"version": "0.2.0", "status": "running"}

    async def get_capabilities(self):
        return {
            "dialogue_api_version": 2,
            "dialogue_events": 1,
            "context_event_batch": 1,
            "director_mode": 1,
            "director_max_participants": 3,
            "tts_jobs": 0,
        }

    async def list_characters(self, force_refresh=False):
        return ["爱慕织姬", "无声铃鹿"]

    async def chat(self, session_id, message, **kwargs):
        self.chat_calls.append(
            {"session_id": session_id, "message": message, **kwargs}
        )
        return "动作：轻轻点头。\n对白：知道了。"

    async def get_history(self, user_uuid, character_name=None, limit=20):
        return list(self.history_messages)

    async def import_history(self, session_id, messages, **kwargs):
        self.import_calls.append(
            {"session_id": session_id, "messages": messages, **kwargs}
        )
        return {"status": "imported"}

    async def clear_history(self, user_uuid, character_name):
        return {"deleted_messages": 4}

    async def list_director_templates(self):
        return [
            {
                "template_id": "city_park_afternoon",
                "name": "城市公园·午后",
                "description": "适合轻松交谈。",
            }
        ]

    async def create_director_session(self, **kwargs):
        return {
            "session_id": "director-1",
            "template": {"template_id": "city_park_afternoon", "name": "城市公园·午后"},
            "participants": [
                {
                    "actor": {
                        "actor_id": "admire_vega",
                        "actor_type": "umamusume",
                        "display_name": "爱慕织姬",
                    }
                }
            ],
            "scene_state": {"location": "城市公园", "time": "午后"},
            "turn_index": 0,
            "events": [],
            "story_outline": kwargs.get("story_outline", ""),
        }

    async def director_turn(self, session_id, user_uuid, events, generate_voice=False):
        self.director_turn_calls.append(
            {"session_id": session_id, "user_uuid": user_uuid, "events": events}
        )
        return {
            "session_id": session_id,
            "turn_index": 1,
            "scene_state": {"location": "城市公园", "time": "午后"},
            "events": [
                {
                    "event_id": "reply-1",
                    "event_type": "character_reply",
                    "actor": {
                        "actor_type": "umamusume",
                        "display_name": "爱慕织姬",
                    },
                    "action": "接过毛巾。",
                    "dialogue": "谢谢。",
                }
            ],
        }

    async def regenerate_director_reply(self, session_id, event_id, user_uuid):
        return {
            "event": {
                "event_id": event_id,
                "event_type": "character_reply",
                "actor": {
                    "actor_type": "umamusume",
                    "display_name": "爱慕织姬",
                },
                "action": "移开视线。",
                "dialogue": "别误会。",
            },
            "scene_state": {"location": "城市公园"},
        }


def _make_bot(agent: _FakeAgent) -> UmamusumeBotClient:
    bot = object.__new__(UmamusumeBotClient)
    bot._agent = agent
    bot._store = ConversationStore()
    return bot


class BotCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_scene_event_is_sent_as_context(self):
        agent = _FakeAgent()
        bot = _make_bot(agent)
        state = bot._store.get("qq-user")
        state.has_seen_welcome = True
        state.selected_character = "爱慕织姬"
        state.session_id = "single-1"

        await bot._handle_user_input("qq-user", "加入环境 夜幕降临")
        reply = await bot._handle_user_input("qq-user", "发送 今天就到这里吧")

        self.assertIn("爱慕织姬", reply)
        call = agent.chat_calls[0]
        self.assertEqual(call["message"], "今天就到这里吧")
        self.assertEqual(
            call["dialogue_event"]["context_events"][0]["event_type"],
            "scene_event",
        )

    async def test_single_reply_can_be_edited_and_regenerated(self):
        agent = _FakeAgent()
        agent.history_messages = [
            {"role": "user", "content": "原来的话", "event_type": "action"},
            {"role": "assistant", "content": "原来的回复"},
        ]
        bot = _make_bot(agent)
        state = bot._store.get("qq-user")
        state.has_seen_welcome = True
        state.selected_character = "爱慕织姬"
        state.session_id = "single-1"

        reply = await bot._handle_user_input("qq-user", "编辑上一句 新的动作")

        self.assertIn("已按新内容重新生成", reply)
        self.assertEqual(agent.import_calls[0]["messages"], [])
        self.assertEqual(agent.chat_calls[0]["dialogue_event"]["event_type"], "action")

    async def test_director_scene_creation_turn_and_regenerate(self):
        agent = _FakeAgent()
        bot = _make_bot(agent)
        state = bot._store.get("qq-user")
        state.has_seen_welcome = True

        await bot._handle_user_input("qq-user", "导演模式")
        created = await bot._handle_user_input(
            "qq-user",
            "创建场景 1 | 爱慕织姬 | 训练后散步",
        )
        turn = await bot._handle_user_input("qq-user", "动作 把毛巾递给她")
        regenerated = await bot._handle_user_input("qq-user", "重新生成")

        self.assertIn("导演场景已创建", created)
        self.assertIn("谢谢", turn)
        self.assertEqual(agent.director_turn_calls[0]["events"][0]["event_type"], "action")
        self.assertIn("别误会", regenerated)


if __name__ == "__main__":
    unittest.main()
