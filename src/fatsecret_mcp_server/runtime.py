"""Backend clients, durable operations, and execution telemetry."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, TypeVar

import requests
from fatsecret import (
    Fatsecret,
    FatsecretWebClient,
    FatsecretWebRateLimitError,
    FatsecretWebVerificationError,
)
from fatsecret.web.service import (
    IdempotencyStore,
    RecipeCopyService,
    RecipeOperationStore,
)
from filelock import FileLock

from .capabilities import serialize
from .credentials import CredentialStore, MemberCredentials, OfficialCredentials
from .settings import Settings
from .telemetry import Telemetry

T = TypeVar("T")


class Runtime:
    def __init__(
        self,
        settings: Settings,
        *,
        credentials: CredentialStore | None = None,
    ) -> None:
        self.settings = settings
        self.credentials = credentials or CredentialStore()
        self._bound_credentials: ContextVar[
            OfficialCredentials | MemberCredentials | None
        ] = ContextVar("fatsecret_bound_credentials", default=None)
        self.session_id = uuid.uuid4().hex
        self._oauth_flows: dict[str, tuple[float, Fatsecret]] = {}
        self._oauth_lock = threading.Lock()
        self._mutation_lock = threading.Lock()
        self._copy_lock = threading.Lock()
        parent_existed = settings.database_path.parent.exists()
        if parent_existed:
            _validate_state_parent(settings.database_path.parent)
        settings.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not parent_existed:
            os.chmod(settings.database_path.parent, 0o700)
        self.telemetry = Telemetry(
            settings.database_path, enabled=settings.telemetry_enabled
        )
        self.idempotency = IdempotencyStore(settings.database_path)
        self.operation_store = RecipeOperationStore(settings.database_path)
        with sqlite3.connect(settings.database_path, timeout=30) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS operation_accounts (
                    operation_id TEXT PRIMARY KEY,
                    account_identity TEXT NOT NULL
                )
                """)
        os.chmod(settings.database_path, 0o600)
        self.copy_service = RecipeCopyService(
            self.web_client,
            self.operation_store,
            default_retry_after=settings.default_retry_after_seconds,
            mutation_lock=self._copy_lock,
            mutation_delay_seconds=settings.mutation_delay_seconds,
        )

    def official_client(self, *, user_session: bool = False) -> Fatsecret:
        bound = self._bound_credentials.get()
        credentials = (
            bound
            if isinstance(bound, OfficialCredentials)
            else self.credentials.official(require_session=user_session)
        )
        session = None
        if credentials.access_token and credentials.access_secret:
            session = (credentials.access_token, credentials.access_secret)
        return Fatsecret(
            credentials.consumer_key,
            credentials.consumer_secret,
            session_token=session,
            retries=True,
            timeout=self.settings.timeout_seconds,
        )

    def web_client(self) -> FatsecretWebClient:
        bound = self._bound_credentials.get()
        credentials = (
            bound if isinstance(bound, MemberCredentials) else self.credentials.member()
        )
        return FatsecretWebClient(
            credentials.username,
            credentials.password,
            timeout=self.settings.timeout_seconds,
            retries=True,
            wait_on_rate_limit=True,
            default_retry_after=self.settings.default_retry_after_seconds,
        )

    def start_oauth(self, callback_url: str = "oob") -> dict[str, str]:
        credentials = self.credentials.official()
        client = Fatsecret(
            credentials.consumer_key,
            credentials.consumer_secret,
            timeout=self.settings.timeout_seconds,
        )
        url = client.get_authorize_url(callback_url)
        flow_id = uuid.uuid4().hex
        now = time.monotonic()
        with self._oauth_lock:
            self._oauth_flows = {
                key: value
                for key, value in self._oauth_flows.items()
                if now - value[0] < 600
            }
            self._oauth_flows[flow_id] = (now, client)
        return {"flow_id": flow_id, "authorization_url": url}

    def complete_oauth(self, flow_id: str, verifier: str) -> dict[str, bool]:
        with self._oauth_lock:
            flow = self._oauth_flows.pop(flow_id, None)
        if flow is None or time.monotonic() - flow[0] >= 600:
            raise RuntimeError("OAuth flow is missing or expired")
        token, secret = flow[1].authenticate(verifier)
        self.credentials.set_oauth_session(token, secret)
        return {"oauth1_session": True}

    def invoke(self, tool_name: str, callback: Callable[[], T]) -> Any:
        started = time.perf_counter()
        try:
            result = callback()
        except Exception:
            self._record(tool_name, "error", started)
            raise
        self._record(tool_name, "success", started)
        return serialize(result)

    def record_resolver(
        self, selected: list[str], started: float, outcome: str
    ) -> None:
        self.telemetry.record(
            session_id=self.session_id,
            tool_name="resolve_fatsecret_capability",
            outcome=outcome,
            duration_ms=(time.perf_counter() - started) * 1000,
            resolver_reach=True,
            selected_tools=",".join(selected),
        )

    def _record(self, tool_name: str, outcome: str, started: float) -> None:
        self.telemetry.record(
            session_id=self.session_id,
            tool_name=tool_name,
            outcome=outcome,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    def idempotent_mutation(
        self,
        *,
        scope: str,
        provider: str,
        key: str,
        payload: object,
        callback: Callable[[], T],
    ) -> Any:
        snapshot = self._credential_snapshot(provider)
        account = self.credentials.account_identity(provider, snapshot)
        durable_scope = f"{provider}:{account}:{scope}"
        existing = self.idempotency.begin(durable_scope, key, payload)
        if existing is not None:
            if existing["state"] == "completed":
                return json.loads(existing["response_json"])
            if existing["state"] == "unknown":
                raise RuntimeError(
                    "previous mutation outcome is unknown; reconcile before retrying: "
                    f"{existing['error']}"
                )
            raise RuntimeError("a mutation with this idempotency key is in progress")
        binding = self._bound_credentials.set(snapshot)
        try:
            with self.mutation_lease(account):
                while True:
                    try:
                        result = callback()
                        break
                    except FatsecretWebRateLimitError as error:
                        delay = (
                            error.retry_after
                            if error.retry_after is not None
                            else self.settings.default_retry_after_seconds
                        )
                        time.sleep(delay)
                    except requests.HTTPError as error:
                        response = error.response
                        if response is None or response.status_code != 429:
                            raise
                        delay = _parse_retry_after(response.headers.get("Retry-After"))
                        time.sleep(
                            delay
                            if delay is not None
                            else self.settings.default_retry_after_seconds
                        )
        except FatsecretWebVerificationError as error:
            self.idempotency.mark_unknown(durable_scope, key, error)
            raise
        except (requests.Timeout, requests.ConnectionError) as error:
            self.idempotency.mark_unknown(durable_scope, key, error)
            raise
        except Exception:
            self._discard_idempotency(durable_scope, key)
            raise
        finally:
            self._bound_credentials.reset(binding)
        serialized = serialize(result)
        self.idempotency.complete(
            durable_scope, key, status_code=200, response=serialized
        )
        return serialized

    def start_copy(
        self, source_recipe_id: int, title: str, idempotency_key: str
    ) -> Any:
        snapshot = self.credentials.member()
        account = self.credentials.account_identity("member", snapshot)
        durable_key = hashlib.sha256(
            f"{account}:{idempotency_key}".encode()
        ).hexdigest()
        binding = self._bound_credentials.set(snapshot)
        try:
            with self.mutation_lease(account):
                operation = self.copy_service.start_copy(
                    source_recipe_id, title, durable_key
                )
                with sqlite3.connect(
                    self.settings.database_path, timeout=30
                ) as connection:
                    connection.execute(
                        "INSERT OR IGNORE INTO operation_accounts "
                        "(operation_id, account_identity) VALUES (?, ?)",
                        (operation.operation_id, account),
                    )
                    connection.commit()
                return self.copy_service.run_copy(operation.operation_id)
        finally:
            self._bound_credentials.reset(binding)

    def get_copy(self, operation_id: str) -> Any:
        snapshot = self.credentials.member()
        account = self.credentials.account_identity("member", snapshot)
        self._assert_operation_account(operation_id, account)
        return self.copy_service.get_copy(operation_id)

    def resume_copy(self, operation_id: str) -> Any:
        snapshot = self.credentials.member()
        account = self.credentials.account_identity("member", snapshot)
        self._assert_operation_account(operation_id, account)
        binding = self._bound_credentials.set(snapshot)
        try:
            with self.mutation_lease(account):
                return self.copy_service.run_copy(operation_id)
        finally:
            self._bound_credentials.reset(binding)

    def _credential_snapshot(
        self, provider: str
    ) -> OfficialCredentials | MemberCredentials:
        if provider == "member":
            return self.credentials.member()
        if provider == "official":
            return self.credentials.official(require_session=True)
        raise ValueError(f"unknown provider: {provider}")

    def _assert_operation_account(self, operation_id: str, account: str) -> None:
        with sqlite3.connect(self.settings.database_path, timeout=30) as connection:
            row = connection.execute(
                "SELECT account_identity FROM operation_accounts "
                "WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None or row[0] != account:
            raise KeyError(operation_id)

    @contextmanager
    def mutation_lease(self, account_identity: str):
        lock_path = self.settings.database_path.with_name(
            f"{self.settings.database_path.name}.{account_identity}.lock"
        )
        lock_path.touch(mode=0o600, exist_ok=True)
        os.chmod(lock_path, 0o600)
        with self._mutation_lock, FileLock(lock_path):
            yield

    def _discard_idempotency(self, scope: str, key: str) -> None:
        with sqlite3.connect(self.settings.database_path, timeout=30) as connection:
            connection.execute(
                "DELETE FROM idempotency_responses "
                "WHERE scope = ? AND idempotency_key = ?",
                (scope, key),
            )
            connection.commit()


def state_database(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _validate_state_parent(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError("state directory must not be a symbolic link")
    status = path.stat()
    getuid = getattr(os, "getuid", None)
    if getuid is not None and status.st_uid != getuid():
        raise RuntimeError("state directory must be owned by the current user")
    if status.st_mode & 0o022:
        raise RuntimeError("state directory must not be group- or world-writable")


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
