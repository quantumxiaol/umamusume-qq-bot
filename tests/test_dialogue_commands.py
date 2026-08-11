from __future__ import annotations

import unittest

from umamusume_qq_bot.dialogue_commands import (
    dialogue_event_fields,
    input_mode_from_history,
    parse_direct_event,
    parse_queue_event,
)


class DialogueCommandTests(unittest.TestCase):
    def test_parses_action_and_environment_events(self):
        action = parse_direct_event("动作 把毛巾递给她")
        environment = parse_direct_event("环境 夜幕降临")

        self.assertEqual(action["event_type"], "action")
        self.assertEqual(action["speaker"]["actor_type"], "trainer")
        self.assertEqual(environment["event_type"], "scene_event")
        self.assertEqual(environment["speaker"]["actor_type"], "narrator")

    def test_prefix_accepts_halfwidth_and_fullwidth_colons(self):
        action = parse_direct_event("动作：把毛巾递给她")
        environment = parse_direct_event("环境: 夜幕降临")
        queued = parse_queue_event("加入对白：今天就练到这里吧")

        self.assertEqual(action["event_type"], "action")
        self.assertEqual(action["content"], "把毛巾递给她")
        self.assertEqual(environment["event_type"], "scene_event")
        self.assertEqual(environment["content"], "夜幕降临")
        self.assertIsNotNone(queued)
        self.assertEqual(queued["content"], "今天就练到这里吧")

    def test_prefix_word_without_separator_remains_dialogue(self):
        event = parse_direct_event("动作片很好看")

        self.assertEqual(event["event_type"], "dialogue")
        self.assertEqual(event["content"], "动作片很好看")

    def test_queue_becomes_context_events(self):
        queued = parse_queue_event("加入环境 开始下起小雨")
        final = parse_direct_event("对白 今天就练到这里吧")

        self.assertIsNotNone(queued)
        fields = dialogue_event_fields(final, [queued])
        self.assertEqual(fields["event_type"], "dialogue")
        self.assertEqual(fields["context_events"][0]["event_type"], "scene_event")

    def test_restores_input_mode_from_history_metadata(self):
        self.assertEqual(
            input_mode_from_history({"event_type": "action"}),
            "action",
        )
        self.assertEqual(
            input_mode_from_history(
                {"actor": {"actor_type": "narrator"}, "event_type": "dialogue"}
            ),
            "scene_event",
        )


if __name__ == "__main__":
    unittest.main()
