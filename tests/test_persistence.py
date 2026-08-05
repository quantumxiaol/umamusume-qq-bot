from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from umamusume_qq_bot.state_store import ConversationStore


class PersistenceTests(unittest.TestCase):
    def test_state_histories_and_director_snapshot_survive_restart(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "bot.sqlite3"
            store = ConversationStore(
                database_path=database_path,
                history_max_messages=3,
            )
            state = store.get("qq-user")
            state.has_seen_welcome = True
            state.selected_character = "爱慕织姬"
            state.session_id = "single-1"
            state.interaction_mode = "director"
            state.director_session_id = "director-1"
            state.director_snapshot = {
                "session_id": "director-1",
                "template": {"name": "城市公园·午后"},
                "participants": [],
                "events": [],
                "turn_index": 0,
            }
            store.append_single_messages(
                state.user_uuid or "",
                state.selected_character,
                [
                    {"role": "user", "content": "第一句"},
                    {"role": "assistant", "content": "第一条回复"},
                    {"role": "user", "content": "第二句"},
                    {"role": "assistant", "content": "第二条回复"},
                ],
            )
            store.save(state)
            store.close()

            restored_store = ConversationStore(
                database_path=database_path,
                history_max_messages=3,
            )
            restored_state = restored_store.get("qq-user")
            history = restored_store.get_single_history(
                restored_state.user_uuid or "",
                "爱慕织姬",
            )
            snapshot = restored_store.get_director_snapshot(
                restored_state.user_uuid or "",
                "director-1",
            )

            self.assertTrue(restored_state.has_seen_welcome)
            self.assertEqual(restored_state.selected_character, "爱慕织姬")
            self.assertEqual(restored_state.session_id, "single-1")
            self.assertEqual(restored_state.interaction_mode, "director")
            self.assertEqual(len(history), 3)
            self.assertEqual(history[0]["content"], "第一条回复")
            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot["template"]["name"], "城市公园·午后")
            restored_store.close()

    def test_clear_and_delete_remove_local_recovery_data(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = ConversationStore(
                database_path=Path(temporary_directory) / "bot.sqlite3",
            )
            state = store.get("qq-user")
            user_uuid = state.user_uuid or ""
            store.append_single_messages(
                user_uuid,
                "爱慕织姬",
                [{"role": "user", "content": "你好"}],
            )
            store.save_director_snapshot(
                user_uuid,
                {"session_id": "director-1", "events": []},
            )

            self.assertEqual(store.clear_single_history(user_uuid, "爱慕织姬"), 1)
            self.assertTrue(store.delete_director_snapshot(user_uuid, "director-1"))
            self.assertEqual(store.get_single_history(user_uuid, "爱慕织姬"), [])
            self.assertIsNone(
                store.get_director_snapshot(user_uuid, "director-1")
            )
            store.close()


if __name__ == "__main__":
    unittest.main()
