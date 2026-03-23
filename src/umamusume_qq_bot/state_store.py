from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class ConversationState:
    user_identity: str | None = None
    user_uuid: str | None = None
    selected_character: str | None = None
    session_id: str | None = None
    has_seen_welcome: bool = False
    awaiting_character_choice: bool = False
    character_options: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class ConversationStore:
    def __init__(self):
        self._states: dict[str, ConversationState] = {}

    def get(self, user_identity: str) -> ConversationState:
        identity = (user_identity or "").strip()
        if not identity:
            raise ValueError("user_identity cannot be empty")

        if identity not in self._states:
            self._states[identity] = ConversationState()
        state = self._states[identity]

        if state.user_identity != identity:
            state.user_identity = identity
            state.user_uuid = self.build_user_uuid(identity)

        state.updated_at = time.time()
        return state

    @staticmethod
    def build_user_uuid(user_identity: str) -> str:
        identity = (user_identity or "").strip()
        if not identity:
            raise ValueError("user_identity cannot be empty")
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"qq-user:{identity}"))
