from __future__ import annotations

import re
from typing import Sequence

MENTION_PATTERN = re.compile(r"<@!?\d+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_group_text(content: str) -> str:
    text = MENTION_PATTERN.sub("", content or "")
    text = WHITESPACE_PATTERN.sub(" ", text)
    return text.strip()


def format_character_choices(characters: Sequence[str], limit: int = 15) -> str:
    if not characters:
        return "暂无可用角色。"
    visible = list(characters[:limit])
    lines = [f"{index}. {name}" for index, name in enumerate(visible, start=1)]
    if len(characters) > limit:
        lines.append(f"... 共 {len(characters)} 个角色，请输入更完整的角色名进行匹配。")
    return "\n".join(lines)


def resolve_character_selection(raw_text: str, options: Sequence[str]) -> str | None:
    text = (raw_text or "").strip()
    if not text or not options:
        return None

    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(options):
            return options[index]

    lower_text = text.lower()
    exact_matches = [item for item in options if item.lower() == lower_text]
    if exact_matches:
        return exact_matches[0]

    contains_matches = [item for item in options if lower_text in item.lower()]
    if len(contains_matches) == 1:
        return contains_matches[0]

    return None


def truncate_reply(text: str, limit: int = 1500) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...(内容过长，已截断)"
