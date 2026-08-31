"""Credential access with environment-first, keyring-backed storage."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from typing import ClassVar

import keyring

SERVICE = "fatsecret-mcp-server"


@dataclass(frozen=True)
class OfficialCredentials:
    consumer_key: str
    consumer_secret: str
    account_id: str | None = None
    access_token: str | None = None
    access_secret: str | None = None


@dataclass(frozen=True)
class MemberCredentials:
    username: str
    password: str


class CredentialStore:
    """Read secrets from environment variables or the operating-system keyring."""

    _environment: ClassVar[dict[str, str]] = {
        "consumer_key": "FATSECRET_CONSUMER_KEY",
        "consumer_secret": "FATSECRET_CONSUMER_SECRET",
        "account_id": "FATSECRET_ACCOUNT_ID",
        "access_token": "FATSECRET_ACCESS_TOKEN",
        "access_secret": "FATSECRET_ACCESS_SECRET",
        "oauth1_session": "FATSECRET_OAUTH1_SESSION",
        "username": "FATSECRET_USERNAME",
        "password": "FATSECRET_PASSWORD",
    }

    def __init__(self) -> None:
        self._write_lock = threading.Lock()

    def get(self, name: str) -> str | None:
        value = os.getenv(self._environment[name])
        return value or keyring.get_password(SERVICE, name)

    def set(self, name: str, value: str) -> None:
        if name not in self._environment:
            raise ValueError(f"unknown credential field: {name}")
        if not value:
            raise ValueError(f"{name} must not be empty")
        keyring.set_password(SERVICE, name, value)

    def official(self, *, require_session: bool = False) -> OfficialCredentials:
        key = self.get("consumer_key")
        secret = self.get("consumer_secret")
        if not key or not secret:
            raise RuntimeError("FatSecret consumer credentials are not configured")
        token = self.get("access_token")
        token_secret = self.get("access_secret")
        bundled = self.get("oauth1_session")
        if bundled:
            session = json.loads(bundled)
            token = session["access_token"]
            token_secret = session["access_secret"]
        if require_session and (not token or not token_secret):
            raise RuntimeError("FatSecret OAuth1 user session is not configured")
        return OfficialCredentials(
            key,
            secret,
            self.get("account_id"),
            token,
            token_secret,
        )

    def set_oauth_session(self, token: str, secret: str) -> None:
        """Atomically replace the OAuth token pair as one keyring value."""
        if not token or not secret:
            raise ValueError("OAuth token and secret must not be empty")
        value = json.dumps(
            {"access_token": token, "access_secret": secret},
            separators=(",", ":"),
        )
        with self._write_lock:
            keyring.set_password(SERVICE, "oauth1_session", value)

    def member(self) -> MemberCredentials:
        username = self.get("username")
        password = self.get("password")
        if not username or not password:
            raise RuntimeError("FatSecret member credentials are not configured")
        return MemberCredentials(username, password)

    def status(self) -> dict[str, bool]:
        return {
            "consumer_credentials": bool(
                self.get("consumer_key") and self.get("consumer_secret")
            ),
            "oauth1_session": bool(
                self.get("oauth1_session")
                or (self.get("access_token") and self.get("access_secret"))
            ),
            "official_account_identity": bool(self.get("account_id")),
            "member_credentials": bool(self.get("username") and self.get("password")),
        }

    def account_identity(
        self,
        provider: str,
        credentials: OfficialCredentials | MemberCredentials | None = None,
    ) -> str:
        """Return a non-secret stable account namespace for durable state."""
        if provider == "member":
            member = (
                credentials
                if isinstance(credentials, MemberCredentials)
                else self.member()
            )
            value = member.username
        elif provider == "official":
            official = (
                credentials
                if isinstance(credentials, OfficialCredentials)
                else self.official(require_session=True)
            )
            if not official.account_id:
                raise RuntimeError(
                    "FATSECRET_ACCOUNT_ID is required for official user mutations"
                )
            value = official.account_id
        else:
            raise ValueError(f"unknown provider: {provider}")
        return hashlib.sha256(f"{provider}:{value}".encode()).hexdigest()[:24]
