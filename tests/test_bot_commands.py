from __future__ import annotations

import unittest
from typing import Any

from umamusume_qq_bot.agent_client import (
    AgentHttpError,
    AgentSessionExpiredError,
    LoadCharacterResult,
)
from umamusume_qq_bot.bot_client import UmamusumeBotClient
from umamusume_qq_bot.state_store import ConversationStore


class _FakeAgent:
    def __init__(self):
        self.chat_calls: list[dict[str, Any]] = []
        self.director_turn_calls: list[dict[str, Any]] = []
        self.import_calls: list[dict[str, Any]] = []
        self.history_messages: list[dict[str, Any]] = []
        self.load_calls: list[dict[str, Any]] = []
        self.recover_calls: list[dict[str, Any]] = []

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

    async def load_character(self, character_name, user_uuid=None):
        self.load_calls.append(
            {"character_name": character_name, "user_uuid": user_uuid}
        )
        return LoadCharacterResult(
            session_id="single-restored",
            user_uuid=user_uuid,
            restored_history_messages=len(self.history_messages),
        )

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

    async def get_director_history(self, user_uuid, limit=20):
        return []

    async def resume_director_history(self, session_id, user_uuid):
        raise AgentHttpError(404, "history missing")

    async def recover_director_session(self, snapshot, user_uuid):
        self.recover_calls.append({"snapshot": snapshot, "user_uuid": user_uuid})
        return snapshot

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

    async def test_existing_hf_history_is_seeded_locally_without_reimport(self):
        agent = _FakeAgent()
        agent.history_messages = [
            {"role": "user", "content": "以前的话"},
            {"role": "assistant", "content": "以前的回复"},
        ]
        bot = _make_bot(agent)
        state = bot._store.get("qq-user")
        state.has_seen_welcome = True
        state.character_options = ["爱慕织姬", "无声铃鹿"]
        state.awaiting_character_choice = True

        reply = await bot._handle_user_input("qq-user", "1")

        self.assertIn("已恢复历史：2 条", reply)
        self.assertEqual(agent.import_calls, [])
        self.assertEqual(
            len(
                bot._store.get_single_history(
                    state.user_uuid or "",
                    "爱慕织姬",
                )
            ),
            2,
        )

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

    async def test_single_history_recovers_after_hf_session_and_files_are_lost(self):
        class _LostSessionAgent(_FakeAgent):
            def __init__(self):
                super().__init__()
                self.chat_attempts = 0

            async def chat(self, session_id, message, **kwargs):
                self.chat_attempts += 1
                if self.chat_attempts == 1:
                    raise AgentSessionExpiredError("session expired")
                return await super().chat(session_id, message, **kwargs)

        agent = _LostSessionAgent()
        bot = _make_bot(agent)
        state = bot._store.get("qq-user")
        state.has_seen_welcome = True
        state.selected_character = "爱慕织姬"
        state.session_id = "expired-session"
        bot._store.append_single_messages(
            state.user_uuid or "",
            state.selected_character,
            [
                {"role": "user", "content": "之前的话"},
                {"role": "assistant", "content": "之前的回复"},
            ],
        )

        reply = await bot._handle_user_input("qq-user", "继续训练吧")

        self.assertIn("知道了", reply)
        self.assertEqual(agent.load_calls[0]["character_name"], "爱慕织姬")
        self.assertEqual(
            [item["content"] for item in agent.import_calls[0]["messages"]],
            ["之前的话", "之前的回复"],
        )
        local_history = bot._store.get_single_history(
            state.user_uuid or "",
            state.selected_character,
        )
        self.assertEqual(len(local_history), 4)

    async def test_director_scene_recovers_from_local_snapshot_after_hf_loss(self):
        class _LostDirectorAgent(_FakeAgent):
            async def director_turn(
                self,
                session_id,
                user_uuid,
                events,
                generate_voice=False,
            ):
                if not self.recover_calls:
                    raise AgentHttpError(404, "session missing")
                return await super().director_turn(
                    session_id,
                    user_uuid,
                    events,
                    generate_voice=generate_voice,
                )

        agent = _LostDirectorAgent()
        bot = _make_bot(agent)
        state = bot._store.get("qq-user")
        state.has_seen_welcome = True
        state.interaction_mode = "director"
        snapshot = await agent.create_director_session(
            character_names=["爱慕织姬"],
            user_uuid=state.user_uuid,
            template_id="city_park_afternoon",
        )
        bot._apply_director_snapshot(state, snapshot)

        history = await bot._handle_user_input("qq-user", "场景历史")

        reply = await bot._handle_user_input("qq-user", "动作 把毛巾递给她")

        self.assertIn("城市公园·午后", history)
        self.assertIn("谢谢", reply)
        self.assertEqual(len(agent.recover_calls), 1)
        self.assertEqual(
            agent.recover_calls[0]["snapshot"]["session_id"],
            "director-1",
        )


if __name__ == "__main__":
    unittest.main()
