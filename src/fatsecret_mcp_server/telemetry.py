"""Local, payload-free tool usage telemetry."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .catalog import POLICY_BY_NAME


class Telemetry:
    def __init__(self, path: Path, *, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self._lock = threading.Lock()
        if not enabled:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS tool_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    inferred_goal TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    resolver_reach INTEGER NOT NULL DEFAULT 0,
                    selected_tools TEXT
                )
                """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def record(
        self,
        *,
        session_id: str,
        tool_name: str,
        outcome: str,
        duration_ms: float,
        resolver_reach: bool = False,
        selected_tools: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        policy = POLICY_BY_NAME[tool_name]
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO tool_events (
                    occurred_at, session_id, tool_name, category, inferred_goal,
                    outcome, duration_ms, resolver_reach, selected_tools
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    session_id,
                    tool_name,
                    policy.category,
                    _goal_for_category(policy.category),
                    outcome,
                    duration_ms,
                    int(resolver_reach),
                    selected_tools,
                ),
            )
            connection.commit()


def _goal_for_category(category: str) -> str:
    return {
        "auth": "authenticate",
        "food": "research_food",
        "recipe": "research_recipe",
        "profile": "inspect_profile",
        "diary": "manage_diary",
        "weight": "inspect_weight",
        "rdi": "manage_rdi",
        "member_recipe": "manage_owned_recipe",
        "discovery": "discover_capability",
    }[category]
