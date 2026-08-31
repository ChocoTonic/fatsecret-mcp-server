import os
import sqlite3
from pathlib import Path

import pytest
import requests
from fatsecret import FatsecretWebIdempotencyConflictError

from fatsecret_mcp_server.credentials import (
    CredentialStore,
    MemberCredentials,
    OfficialCredentials,
)
from fatsecret_mcp_server.runtime import Runtime
from fatsecret_mcp_server.settings import Settings


class StubCredentials(CredentialStore):
    def __init__(self, identity: str = "test") -> None:
        self.identity = identity

    def member(self) -> MemberCredentials:
        return MemberCredentials(f"{self.identity}-member", "password")

    def official(self, *, require_session: bool = False) -> OfficialCredentials:
        return OfficialCredentials(
            "key",
            "secret",
            f"{self.identity}-official",
            f"{self.identity}-token",
            f"{self.identity}-token-secret",
        )


def runtime(tmp_path: Path) -> Runtime:
    return Runtime(
        Settings(database_path=tmp_path / "state.sqlite3"),
        credentials=StubCredentials(),
    )


def test_successful_mutation_is_replayed(tmp_path: Path) -> None:
    execution = runtime(tmp_path)
    calls = 0

    def mutate() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"recipe_id": 42}

    first = execution.idempotent_mutation(
        scope="test",
        provider="member",
        key="same-key",
        payload={"value": 1},
        callback=mutate,
    )
    second = execution.idempotent_mutation(
        scope="test",
        provider="member",
        key="same-key",
        payload={"value": 1},
        callback=mutate,
    )

    assert first == second == {"recipe_id": 42}
    assert calls == 1


def test_idempotency_key_rejects_another_payload(tmp_path: Path) -> None:
    execution = runtime(tmp_path)
    execution.idempotent_mutation(
        scope="test",
        provider="member",
        key="same-key",
        payload={"value": 1},
        callback=lambda: True,
    )
    with pytest.raises(FatsecretWebIdempotencyConflictError):
        execution.idempotent_mutation(
            scope="test",
            provider="member",
            key="same-key",
            payload={"value": 2},
            callback=lambda: True,
        )


def test_telemetry_does_not_store_payloads(tmp_path: Path) -> None:
    execution = runtime(tmp_path)
    execution.invoke("get_food", lambda: {"secret_food": "not persisted"})

    with sqlite3.connect(execution.settings.database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tool_events)")
        }
        stored = connection.execute(
            "SELECT tool_name, inferred_goal FROM tool_events"
        ).fetchone()

    assert "arguments" not in columns
    assert "result" not in columns
    assert stored == ("get_food", "research_food")


def test_explicit_rate_limit_waits_and_retries_same_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution = runtime(tmp_path)
    attempts = 0
    delays: list[float] = []

    def mutate() -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "17"
            raise requests.HTTPError(response=response)
        return True

    monkeypatch.setattr("fatsecret_mcp_server.runtime.time.sleep", delays.append)
    result = execution.idempotent_mutation(
        scope="test",
        provider="member",
        key="rate-limit-key",
        payload={},
        callback=mutate,
    )

    assert result is True
    assert attempts == 2
    assert delays == [17.0]


def test_definitive_failure_releases_idempotency_key(tmp_path: Path) -> None:
    execution = runtime(tmp_path)
    with pytest.raises(ValueError):
        execution.idempotent_mutation(
            scope="test",
            provider="member",
            key="retryable-key",
            payload={},
            callback=lambda: (_ for _ in ()).throw(ValueError("rejected")),
        )

    assert (
        execution.idempotent_mutation(
            scope="test",
            provider="member",
            key="retryable-key",
            payload={},
            callback=lambda: True,
        )
        is True
    )


def test_state_permissions_are_private(tmp_path: Path) -> None:
    state_directory = tmp_path / "new-private-directory"
    execution = runtime(state_directory)
    assert execution.settings.database_path.stat().st_mode & 0o777 == 0o600
    assert execution.settings.database_path.parent.stat().st_mode & 0o777 == 0o700


def test_insecure_existing_state_directory_is_rejected(tmp_path: Path) -> None:
    state_directory = tmp_path / "insecure"
    state_directory.mkdir(mode=0o777)
    os.chmod(state_directory, 0o777)

    with pytest.raises(RuntimeError, match="group- or world-writable"):
        runtime(state_directory)


def test_idempotency_is_namespaced_by_account(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "shared.sqlite3")
    first = Runtime(settings, credentials=StubCredentials("first"))
    second = Runtime(settings, credentials=StubCredentials("second"))
    calls: list[str] = []

    for execution, account in ((first, "first"), (second, "second")):
        execution.idempotent_mutation(
            scope="test",
            provider="member",
            key="shared-key",
            payload={},
            callback=lambda account=account: calls.append(account),
        )

    assert calls == ["first", "second"]


def test_mutation_uses_one_credential_snapshot(tmp_path: Path) -> None:
    credentials = StubCredentials("first")
    execution = Runtime(
        Settings(database_path=tmp_path / "snapshot.sqlite3"),
        credentials=credentials,
    )

    def mutate() -> str | None:
        credentials.identity = "second"
        return execution.official_client(user_session=True).access_token

    result = execution.idempotent_mutation(
        scope="test",
        provider="official",
        key="snapshot-key",
        payload={},
        callback=mutate,
    )

    assert result == "first-token"
