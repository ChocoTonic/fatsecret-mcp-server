"""Credential access with environment-first, keyring-backed storage."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import ClassVar

import keyring

SERVICE = "fatsecret-mcp-server"


@dataclass(frozen=True)
class OfficialCredentials:
    consumer_key: str
    consumer_secret: str
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
        "access_token": "FATSECRET_ACCESS_TOKEN",
        "access_secret": "FATSECRET_ACCESS_SECRET",
        "username": "FATSECRET_USERNAME",
        "password": "FATSECRET_PASSWORD",
    }

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
        if require_session and (not token or not token_secret):
            raise RuntimeError("FatSecret OAuth1 user session is not configured")
        return OfficialCredentials(key, secret, token, token_secret)

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
                self.get("access_token") and self.get("access_secret")
            ),
            "member_credentials": bool(self.get("username") and self.get("password")),
        }

    def account_identity(self, provider: str) -> str:
        """Return a non-secret stable account namespace for durable state."""
        if provider == "member":
            value = self.member().username
        elif provider == "official":
            credentials = self.official(require_session=True)
            value = credentials.access_token or ""
        else:
            raise ValueError(f"unknown provider: {provider}")
        return hashlib.sha256(f"{provider}:{value}".encode()).hexdigest()[:24]
