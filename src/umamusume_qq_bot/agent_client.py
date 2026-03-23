from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

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
    def __init__(self, base_url: str, timeout_seconds: float, characters_cache_ttl_seconds: int = 300):
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._characters_cache_ttl_seconds = characters_cache_ttl_seconds
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

    async def chat(self, session_id: str, message: str, text_only: bool = False) -> str:
        payload = {
            "session_id": session_id,
            "message": message,
            "text_only": text_only,
        }
        try:
            data = await self._request_json("POST", "/chat", payload=payload)
        except AgentHttpError as exc:
            if exc.status == 404:
                raise AgentSessionExpiredError("session expired") from exc
            raise
        return self._extract_reply(data)

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
        if isinstance(data, dict):
            for key in ("reply", "message", "text"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return json.dumps(data, ensure_ascii=False)
        if isinstance(data, str):
            return data
        return str(data)
