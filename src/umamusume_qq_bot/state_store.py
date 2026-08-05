from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .persistence import LocalDatabase


@dataclass
class ConversationState:
    user_identity: str | None = None
    user_uuid: str | None = None
    selected_character: str | None = None
    session_id: str | None = None
    has_seen_welcome: bool = False
    awaiting_character_choice: bool = False
    character_options: list[str] = field(default_factory=list)
    interaction_mode: str = "single"
    queued_events: list[dict[str, Any]] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    director_session_id: str | None = None
    director_snapshot: dict[str, Any] | None = None
    director_templates: list[dict[str, Any]] = field(default_factory=list)
    director_history_options: list[dict[str, Any]] = field(default_factory=list)
    last_director_event_id: str | None = None
    updated_at: float = field(default_factory=time.time)


class ConversationStore:
    def __init__(
        self,
        database_path: str | Path | None = None,
        history_max_messages: int = 1000,
    ):
        self._states: dict[str, ConversationState] = {}
        self._single_histories: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._director_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
        self._history_max_messages = max(0, int(history_max_messages))
        self._database = (
            LocalDatabase(database_path, history_max_messages=self._history_max_messages)
            if database_path is not None
            else None
        )

    def get(self, user_identity: str) -> ConversationState:
        identity = (user_identity or "").strip()
        if not identity:
            raise ValueError("user_identity cannot be empty")

        if identity not in self._states:
            state = ConversationState(
                user_identity=identity,
                user_uuid=self.build_user_uuid(identity),
            )
            if self._database is not None:
                persisted = self._database.load_user_state(identity)
                if persisted is not None:
                    self._restore_state(state, persisted)
            self._states[identity] = state
        state = self._states[identity]

        if state.user_identity != identity:
            state.user_identity = identity
            state.user_uuid = self.build_user_uuid(identity)

        state.updated_at = time.time()
        return state

    def save(self, state: ConversationState) -> None:
        if not state.user_identity or not state.user_uuid:
            return
        if self._database is not None:
            self._database.save_user_state(
                state.user_identity,
                state.user_uuid,
                self._state_payload(state),
                state.updated_at,
            )
        if state.director_snapshot and state.director_session_id:
            self.save_director_snapshot(state.user_uuid, state.director_snapshot)

    def get_single_history(
        self,
        user_uuid: str,
        character_name: str,
    ) -> list[dict[str, Any]]:
        if self._database is not None:
            return self._database.get_single_history(user_uuid, character_name)
        return copy.deepcopy(self._single_histories.get((user_uuid, character_name), []))

    def replace_single_history(
        self,
        user_uuid: str,
        character_name: str,
        messages: list[dict[str, Any]],
    ) -> None:
        if self._database is not None:
            self._database.replace_single_history(user_uuid, character_name, messages)
            return
        normalized = copy.deepcopy([item for item in messages if isinstance(item, dict)])
        if self._history_max_messages > 0:
            normalized = normalized[-self._history_max_messages :]
        self._single_histories[(user_uuid, character_name)] = normalized

    def append_single_messages(
        self,
        user_uuid: str,
        character_name: str,
        messages: list[dict[str, Any]],
    ) -> None:
        if self._database is not None:
            self._database.append_single_messages(user_uuid, character_name, messages)
            return
        history = self._single_histories.setdefault((user_uuid, character_name), [])
        history.extend(copy.deepcopy([item for item in messages if isinstance(item, dict)]))
        if self._history_max_messages > 0 and len(history) > self._history_max_messages:
            del history[: len(history) - self._history_max_messages]

    def clear_single_history(self, user_uuid: str, character_name: str) -> int:
        if self._database is not None:
            return self._database.clear_single_history(user_uuid, character_name)
        return len(self._single_histories.pop((user_uuid, character_name), []))

    def save_director_snapshot(
        self,
        user_uuid: str,
        snapshot: dict[str, Any],
    ) -> None:
        session_id = str(snapshot.get("session_id", "")).strip()
        if not session_id:
            return
        if self._database is not None:
            self._database.save_director_snapshot(user_uuid, snapshot)
            return
        self._director_snapshots[(user_uuid, session_id)] = copy.deepcopy(snapshot)

    def get_director_snapshot(
        self,
        user_uuid: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        if self._database is not None:
            return self._database.get_director_snapshot(user_uuid, session_id)
        snapshot = self._director_snapshots.get((user_uuid, session_id))
        return copy.deepcopy(snapshot) if snapshot is not None else None

    def list_director_snapshots(
        self,
        user_uuid: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if self._database is not None:
            return self._database.list_director_snapshots(user_uuid, limit=limit)
        snapshots = [
            copy.deepcopy(snapshot)
            for (stored_user_uuid, _), snapshot in reversed(
                list(self._director_snapshots.items())
            )
            if stored_user_uuid == user_uuid
        ]
        return snapshots[: max(1, int(limit))]

    def delete_director_snapshot(self, user_uuid: str, session_id: str) -> bool:
        if self._database is not None:
            return self._database.delete_director_snapshot(user_uuid, session_id)
        return self._director_snapshots.pop((user_uuid, session_id), None) is not None

    def close(self) -> None:
        if self._database is not None:
            self._database.close()

    @staticmethod
    def _state_payload(state: ConversationState) -> dict[str, Any]:
        return {
            "user_uuid": state.user_uuid,
            "selected_character": state.selected_character,
            "session_id": state.session_id,
            "has_seen_welcome": state.has_seen_welcome,
            "awaiting_character_choice": state.awaiting_character_choice,
            "interaction_mode": state.interaction_mode,
            "queued_events": state.queued_events,
            "director_session_id": state.director_session_id,
            "director_snapshot": state.director_snapshot,
            "last_director_event_id": state.last_director_event_id,
            "updated_at": state.updated_at,
        }

    @staticmethod
    def _restore_state(state: ConversationState, payload: dict[str, Any]) -> None:
        user_uuid = str(payload.get("user_uuid", "")).strip()
        if user_uuid:
            state.user_uuid = user_uuid
        selected_character = payload.get("selected_character")
        state.selected_character = (
            str(selected_character).strip() if selected_character else None
        )
        session_id = payload.get("session_id")
        state.session_id = str(session_id).strip() if session_id else None
        state.has_seen_welcome = bool(payload.get("has_seen_welcome", False))
        state.awaiting_character_choice = bool(
            payload.get("awaiting_character_choice", False)
        )
        interaction_mode = str(payload.get("interaction_mode", "single"))
        state.interaction_mode = (
            interaction_mode if interaction_mode in {"single", "director"} else "single"
        )
        queued_events = payload.get("queued_events")
        state.queued_events = (
            [item for item in queued_events if isinstance(item, dict)]
            if isinstance(queued_events, list)
            else []
        )
        director_session_id = payload.get("director_session_id")
        state.director_session_id = (
            str(director_session_id).strip() if director_session_id else None
        )
        director_snapshot = payload.get("director_snapshot")
        state.director_snapshot = (
            director_snapshot if isinstance(director_snapshot, dict) else None
        )
        last_event_id = payload.get("last_director_event_id")
        state.last_director_event_id = (
            str(last_event_id).strip() if last_event_id else None
        )
        try:
            state.updated_at = float(payload.get("updated_at", time.time()))
        except (TypeError, ValueError):
            state.updated_at = time.time()

    @staticmethod
    def build_user_uuid(user_identity: str) -> str:
        identity = (user_identity or "").strip()
        if not identity:
            raise ValueError("user_identity cannot be empty")
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"qq-user:{identity}"))
