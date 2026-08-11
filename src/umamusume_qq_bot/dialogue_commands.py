from __future__ import annotations

from typing import Any


INPUT_MODES: dict[str, dict[str, Any]] = {
    "dialogue": {
        "label": "对白",
        "event_type": "dialogue",
        "speaker": {
            "actor_id": "player",
            "actor_type": "trainer",
            "display_name": "训练员",
            "role_in_scene": "trainer",
        },
    },
    "action": {
        "label": "动作",
        "event_type": "action",
        "speaker": {
            "actor_id": "player",
            "actor_type": "trainer",
            "display_name": "训练员",
            "role_in_scene": "trainer",
        },
    },
    "scene_event": {
        "label": "环境",
        "event_type": "scene_event",
        "speaker": {
            "actor_id": "narrator",
            "actor_type": "narrator",
            "display_name": "环境",
            "role_in_scene": "environment",
        },
    },
}

MODE_PREFIXES = {
    "对白": "dialogue",
    "动作": "action",
    "环境": "scene_event",
}

PREFIX_SEPARATORS = " \u3000:："


def _content_after_prefix(text: str, prefix: str) -> str | None:
    if not text.startswith(prefix):
        return None
    suffix = text[len(prefix) :]
    if not suffix or suffix[0] not in PREFIX_SEPARATORS:
        return None
    content = suffix.lstrip(PREFIX_SEPARATORS)
    return content or None


def build_dialogue_event(content: str, input_mode: str = "dialogue") -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ValueError("event content cannot be empty")
    mode = INPUT_MODES.get(input_mode, INPUT_MODES["dialogue"])
    return {
        "content": text,
        "input_mode": input_mode if input_mode in INPUT_MODES else "dialogue",
        "speaker": dict(mode["speaker"]),
        "event_type": mode["event_type"],
    }


def parse_direct_event(text: str) -> dict[str, Any]:
    normalized = (text or "").strip()
    for prefix, input_mode in MODE_PREFIXES.items():
        content = _content_after_prefix(normalized, prefix)
        if content is not None:
            return build_dialogue_event(content, input_mode)
    return build_dialogue_event(normalized, "dialogue")


def parse_queue_event(text: str) -> dict[str, Any] | None:
    normalized = (text or "").strip()
    for prefix, input_mode in MODE_PREFIXES.items():
        content = _content_after_prefix(normalized, f"加入{prefix}")
        if content is not None:
            return build_dialogue_event(content, input_mode)
    return None


def event_for_request(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": str(event.get("content", "")).strip(),
        "speaker": event.get("speaker"),
        "event_type": event.get("event_type"),
    }


def dialogue_event_fields(
    final_event: dict[str, Any],
    context_events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "speaker": final_event.get("speaker"),
        "event_type": final_event.get("event_type"),
        "context_events": [event_for_request(event) for event in context_events],
    }


def input_mode_from_history(message: dict[str, Any]) -> str:
    event_type = str(message.get("event_type", "")).strip()
    actor = message.get("actor") or message.get("speaker")
    actor_type = actor.get("actor_type") if isinstance(actor, dict) else ""
    if event_type in {"scene_event", "narration"} or actor_type == "narrator":
        return "scene_event"
    if event_type == "action":
        return "action"
    return "dialogue"


def format_queued_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return "待发送队列为空。"
    lines = [f"待发送事件（{len(events)} 条）："]
    for index, event in enumerate(events, start=1):
        input_mode = str(event.get("input_mode", "dialogue"))
        label = str(INPUT_MODES.get(input_mode, INPUT_MODES["dialogue"])["label"])
        content = str(event.get("content", "")).strip()
        if len(content) > 80:
            content = f"{content[:80]}..."
        lines.append(f"{index}. [{label}] {content}")
    lines.append("发送「发送 <最后一句对白>」，或仅发送「发送」使用队列最后一条。")
    return "\n".join(lines)
