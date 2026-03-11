from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ConversationState:
    selected_character: str | None = None
    session_id: str | None = None
    awaiting_character_choice: bool = False
    character_options: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class ConversationStore:
    def __init__(self):
        self._states: dict[tuple[str, str], ConversationState] = {}

    def get(self, group_openid: str, member_openid: str) -> ConversationState:
        key = (group_openid, member_openid)
        if key not in self._states:
            self._states[key] = ConversationState()
        state = self._states[key]
        state.updated_at = time.time()
        return state
