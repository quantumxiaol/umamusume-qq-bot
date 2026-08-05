from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class LocalDatabase:
    """Small SQLite store for durable bot state and Agent recovery data."""

    def __init__(self, path: str | Path, history_max_messages: int = 1000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.history_max_messages = max(0, int(history_max_messages))
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path,
            timeout=10,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._initialize()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("PRAGMA busy_timeout=5000")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_states (
                    user_identity TEXT PRIMARY KEY,
                    user_uuid TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS single_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uuid TEXT NOT NULL,
                    character_name TEXT NOT NULL,
                    message_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_single_messages_lookup
                ON single_messages(user_uuid, character_name, id);

                CREATE TABLE IF NOT EXISTS director_snapshots (
                    user_uuid TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_uuid, session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_director_snapshots_updated
                ON director_snapshots(user_uuid, updated_at DESC);

                PRAGMA user_version=1;
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def load_user_state(self, user_identity: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json FROM user_states WHERE user_identity = ?",
                (user_identity,),
            ).fetchone()
        if row is None:
            return None
        return self._decode_object(row["state_json"])

    def save_user_state(
        self,
        user_identity: str,
        user_uuid: str,
        state: dict[str, Any],
        updated_at: float,
    ) -> None:
        encoded = self._encode(state)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO user_states(user_identity, user_uuid, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_identity) DO UPDATE SET
                    user_uuid = excluded.user_uuid,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (user_identity, user_uuid, encoded, updated_at),
            )

    def get_single_history(
        self,
        user_uuid: str,
        character_name: str,
    ) -> list[dict[str, Any]]:
        limit_clause = ""
        parameters: list[Any] = [user_uuid, character_name]
        if self.history_max_messages > 0:
            limit_clause = " LIMIT ?"
            parameters.append(self.history_max_messages)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT message_json FROM (
                    SELECT id, message_json
                    FROM single_messages
                    WHERE user_uuid = ? AND character_name = ?
                    ORDER BY id DESC
                """
                + limit_clause
                + ") ORDER BY id ASC",
                parameters,
            ).fetchall()
        return [
            decoded
            for row in rows
            if (decoded := self._decode_object(row["message_json"])) is not None
        ]

    def replace_single_history(
        self,
        user_uuid: str,
        character_name: str,
        messages: list[dict[str, Any]],
    ) -> None:
        normalized = [item for item in messages if isinstance(item, dict)]
        if self.history_max_messages > 0:
            normalized = normalized[-self.history_max_messages :]
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM single_messages WHERE user_uuid = ? AND character_name = ?",
                (user_uuid, character_name),
            )
            self._connection.executemany(
                """
                INSERT INTO single_messages(
                    user_uuid, character_name, message_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (user_uuid, character_name, self._encode(message), now + index * 1e-6)
                    for index, message in enumerate(normalized)
                ],
            )

    def append_single_messages(
        self,
        user_uuid: str,
        character_name: str,
        messages: list[dict[str, Any]],
    ) -> None:
        normalized = [item for item in messages if isinstance(item, dict)]
        if not normalized:
            return
        now = time.time()
        with self._lock, self._connection:
            self._connection.executemany(
                """
                INSERT INTO single_messages(
                    user_uuid, character_name, message_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (user_uuid, character_name, self._encode(message), now + index * 1e-6)
                    for index, message in enumerate(normalized)
                ],
            )
            self._prune_single_history(user_uuid, character_name)

    def _prune_single_history(self, user_uuid: str, character_name: str) -> None:
        if self.history_max_messages <= 0:
            return
        self._connection.execute(
            """
            DELETE FROM single_messages
            WHERE user_uuid = ? AND character_name = ?
              AND id NOT IN (
                  SELECT id FROM single_messages
                  WHERE user_uuid = ? AND character_name = ?
                  ORDER BY id DESC LIMIT ?
              )
            """,
            (
                user_uuid,
                character_name,
                user_uuid,
                character_name,
                self.history_max_messages,
            ),
        )

    def clear_single_history(self, user_uuid: str, character_name: str) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM single_messages WHERE user_uuid = ? AND character_name = ?",
                (user_uuid, character_name),
            )
        return max(0, cursor.rowcount)

    def save_director_snapshot(
        self,
        user_uuid: str,
        snapshot: dict[str, Any],
    ) -> None:
        session_id = str(snapshot.get("session_id", "")).strip()
        if not session_id:
            raise ValueError("director snapshot is missing session_id")
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO director_snapshots(
                    user_uuid, session_id, snapshot_json, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_uuid, session_id) DO UPDATE SET
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
                """,
                (user_uuid, session_id, self._encode(snapshot), now),
            )

    def get_director_snapshot(
        self,
        user_uuid: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT snapshot_json FROM director_snapshots
                WHERE user_uuid = ? AND session_id = ?
                """,
                (user_uuid, session_id),
            ).fetchone()
        if row is None:
            return None
        return self._decode_object(row["snapshot_json"])

    def list_director_snapshots(
        self,
        user_uuid: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT snapshot_json FROM director_snapshots
                WHERE user_uuid = ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (user_uuid, max(1, int(limit))),
            ).fetchall()
        return [
            decoded
            for row in rows
            if (decoded := self._decode_object(row["snapshot_json"])) is not None
        ]

    def delete_director_snapshot(self, user_uuid: str, session_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                DELETE FROM director_snapshots
                WHERE user_uuid = ? AND session_id = ?
                """,
                (user_uuid, session_id),
            )
        return cursor.rowcount > 0

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    @staticmethod
    def _decode_object(value: str) -> dict[str, Any] | None:
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
        return decoded if isinstance(decoded, dict) else None
