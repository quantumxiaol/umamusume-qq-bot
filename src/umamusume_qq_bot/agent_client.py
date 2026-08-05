from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp


class AgentError(RuntimeError):
    pass


class AgentHttpError(AgentError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Agent HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class AgentSessionExpiredError(AgentError):
    pass


@dataclass(frozen=True)
class LoadCharacterResult:
    session_id: str
    user_uuid: str | None = None
    restored_history_messages: int = 0


class AgentClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        characters_cache_ttl_seconds: int = 300,
        api_access_key: str = "",
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._characters_cache_ttl_seconds = characters_cache_ttl_seconds
        normalized_api_access_key = api_access_key.strip()
        self._headers = (
            {"X-API-Key": normalized_api_access_key}
            if normalized_api_access_key
            else None
        )
        self._characters_cache: tuple[float, list[str]] | None = None
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def list_characters(self, force_refresh: bool = False) -> list[str]:
        now = time.monotonic()
        if (
            not force_refresh
            and self._characters_cache is not None
            and now - self._characters_cache[0] < self._characters_cache_ttl_seconds
        ):
            return list(self._characters_cache[1])

        data = await self._request_json("GET", "/characters")
        characters = self._extract_characters(data)
        self._characters_cache = (now, characters)
        return list(characters)

    async def load_character(self, character_name: str, user_uuid: str | None = None) -> LoadCharacterResult:
        payload = {"character_name": character_name}
        if user_uuid:
            payload["user_uuid"] = user_uuid
        data = await self._request_json("POST", "/load_character", payload=payload)
        if not isinstance(data, dict):
            raise AgentError("Invalid response from /load_character")
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            raise AgentError("Missing session_id in /load_character response")

        restored_history_messages = data.get("restored_history_messages", 0)
        try:
            restored_history_messages = int(restored_history_messages)
        except (TypeError, ValueError):
            restored_history_messages = 0

        response_user_uuid = str(data.get("user_uuid", "")).strip() or None
        return LoadCharacterResult(
            session_id=session_id,
            user_uuid=response_user_uuid,
            restored_history_messages=max(restored_history_messages, 0),
        )

    async def get_status(self) -> dict[str, Any]:
        data = await self._request_json("GET", "/")
        if not isinstance(data, dict):
            raise AgentError("Invalid response from /")
        return data

    async def get_capabilities(self) -> dict[str, Any]:
        try:
            data = await self._request_json("GET", "/capabilities")
        except AgentHttpError as exc:
            if exc.status == 404:
                return {}
            raise
        if not isinstance(data, dict):
            raise AgentError("Invalid response from /capabilities")
        return data

    async def chat(
        self,
        session_id: str,
        message: str,
        text_only: bool = False,
        generate_voice: bool = False,
        dialogue_event: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "session_id": session_id,
            "message": message,
            "text_only": text_only,
            "generate_voice": generate_voice,
        }
        if dialogue_event:
            for key in (
                "speaker",
                "event_type",
                "target_actor_ids",
                "context_events",
            ):
                value = dialogue_event.get(key)
                if value is not None:
                    payload[key] = value
        try:
            data = await self._request_json("POST", "/chat", payload=payload)
        except AgentHttpError as exc:
            if exc.status == 404:
                raise AgentSessionExpiredError("session expired") from exc
            raise
        return self._extract_reply(data)

    async def import_history(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        replace_current: bool = True,
        source: str = "qq_bot",
    ) -> dict[str, Any]:
        data = await self._request_json(
            "POST",
            "/history/import",
            payload={
                "session_id": session_id,
                "messages": messages,
                "replace_current": replace_current,
                "source": source,
            },
        )
        if not isinstance(data, dict):
            raise AgentError("Invalid response from /history/import")
        return data

    async def clear_history(self, user_uuid: str, character_name: str) -> dict[str, Any]:
        data = await self._request_json(
            "DELETE",
            "/history",
            params={"user_uuid": user_uuid, "character_name": character_name},
        )
        if not isinstance(data, dict):
            raise AgentError("Invalid response from DELETE /history")
        return data

    async def list_director_templates(self) -> list[dict[str, Any]]:
        data = await self._request_json("GET", "/director/templates")
        if not isinstance(data, dict):
            raise AgentError("Invalid response from /director/templates")
        templates = data.get("templates")
        if not isinstance(templates, list):
            return []
        return [item for item in templates if isinstance(item, dict)]

    async def create_director_session(
        self,
        character_names: list[str],
        user_uuid: str,
        template_id: str | None = None,
        custom_scene: dict[str, Any] | None = None,
        story_outline: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "character_names": character_names,
            "user_uuid": user_uuid,
            "story_outline": story_outline,
        }
        if template_id:
            payload["template_id"] = template_id
        if custom_scene:
            payload["custom_scene"] = custom_scene
        return await self._request_dict("POST", "/director/sessions", payload=payload)

    async def director_turn(
        self,
        session_id: str,
        user_uuid: str,
        events: list[dict[str, Any]],
        generate_voice: bool = False,
    ) -> dict[str, Any]:
        return await self._request_dict(
            "POST",
            "/director/turn",
            payload={
                "session_id": session_id,
                "user_uuid": user_uuid,
                "events": events,
                "generate_voice": generate_voice,
            },
        )

    async def get_director_history(self, user_uuid: str, limit: int = 20) -> list[dict[str, Any]]:
        data = await self._request_dict(
            "GET",
            "/director/history",
            params={"user_uuid": user_uuid, "limit": max(1, limit)},
        )
        scenes = data.get("scenes")
        if not isinstance(scenes, list):
            return []
        return [item for item in scenes if isinstance(item, dict)]

    async def resume_director_history(self, session_id: str, user_uuid: str) -> dict[str, Any]:
        encoded_session_id = quote(session_id, safe="")
        return await self._request_dict(
            "POST",
            f"/director/history/{encoded_session_id}/resume",
            payload={"user_uuid": user_uuid},
        )

    async def recover_director_session(
        self,
        snapshot: dict[str, Any],
        user_uuid: str,
    ) -> dict[str, Any]:
        return await self._request_dict(
            "POST",
            "/director/sessions/recover",
            payload={"user_uuid": user_uuid, "snapshot": snapshot},
        )

    async def delete_director_session(self, session_id: str, user_uuid: str) -> dict[str, Any]:
        encoded_session_id = quote(session_id, safe="")
        return await self._request_dict(
            "DELETE",
            f"/director/sessions/{encoded_session_id}",
            params={"user_uuid": user_uuid},
        )

    async def delete_director_history(self, session_id: str, user_uuid: str) -> dict[str, Any]:
        encoded_session_id = quote(session_id, safe="")
        return await self._request_dict(
            "DELETE",
            f"/director/history/{encoded_session_id}",
            params={"user_uuid": user_uuid},
        )

    async def regenerate_director_reply(
        self,
        session_id: str,
        event_id: str,
        user_uuid: str,
        generate_voice: bool = False,
    ) -> dict[str, Any]:
        encoded_session_id = quote(session_id, safe="")
        encoded_event_id = quote(event_id, safe="")
        return await self._request_dict(
            "POST",
            f"/director/sessions/{encoded_session_id}/events/{encoded_event_id}/regenerate",
            payload={
                "user_uuid": user_uuid,
                "generate_voice": generate_voice,
            },
        )

    async def get_history(self, user_uuid: str, character_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"user_uuid": user_uuid}
        if character_name:
            params["character_name"] = character_name
        params["limit"] = max(limit, 0)

        data = await self._request_json("GET", "/history", params=params)
        if not isinstance(data, dict):
            raise AgentError("Invalid response from /history")
        messages = data.get("messages")
        if not isinstance(messages, list):
            return []
        return [item for item in messages if isinstance(item, dict)]

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        session = await self._get_session()
        url = f"{self._base_url}{path}"
        async with session.request(
            method=method,
            url=url,
            json=payload,
            params=params,
            headers=self._headers,
            timeout=self._timeout,
        ) as response:
            body = await response.text()
            if response.status >= 400:
                raise AgentHttpError(response.status, body)
            if not body:
                return {}
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise AgentError(f"Non-JSON response from {path}: {body[:200]}") from exc

    async def _request_dict(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = await self._request_json(method, path, payload=payload, params=params)
        if not isinstance(data, dict):
            raise AgentError(f"Invalid response from {path}")
        return data

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @staticmethod
    def _extract_characters(data: Any) -> list[str]:
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
        if isinstance(data, dict):
            for key in ("characters", "data", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return [str(item).strip() for item in value if str(item).strip()]
        raise AgentError("Invalid /characters response shape")

    @staticmethod
    def _extract_reply(data: Any) -> str:
        if isinstance(data, str):
            if data.strip():
                return data
            raise AgentError("Empty response from /chat")

        if isinstance(data, dict):
            # Legacy backends returned a plain string in one of these fields.
            for key in ("reply", "text", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value

            # JSON reply v2 returns action/dialogue at the top level. Some
            # compatible servers expose the same fields only in message/reply.
            structured_sources = [data]
            for key in ("message", "reply"):
                value = data.get(key)
                if isinstance(value, dict):
                    structured_sources.append(value)

            for source in structured_sources:
                dialogue = source.get("dialogue")
                if not isinstance(dialogue, str) or not dialogue.strip():
                    dialogue = source.get("content")
                if not isinstance(dialogue, str) or not dialogue.strip():
                    continue

                action = source.get("action")
                if isinstance(action, str) and action.strip():
                    return f"动作：{action.strip()}\n对白：{dialogue.strip()}"
                return dialogue.strip()

        raise AgentError("Invalid response from /chat: missing reply text")
