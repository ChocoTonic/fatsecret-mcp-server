"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

from platformdirs import user_data_path
from pydantic import BaseModel, ConfigDict, Field

Profile = Literal["default", "member", "discovery", "diary", "bootstrap", "full"]


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: Profile = "default"
    database_path: Path = Field(
        default_factory=lambda: user_data_path("fatsecret-mcp-server") / "state.sqlite3"
    )
    timeout_seconds: float = Field(default=30, gt=0)
    default_retry_after_seconds: int = Field(default=300, gt=0)
    mutation_delay_seconds: float = Field(default=1.0, ge=0)
    allow_credential_tools: bool = False
    telemetry_enabled: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            profile=cast(Profile, os.getenv("FATSECRET_MCP_PROFILE", "default")),
            database_path=Path(
                os.getenv(
                    "FATSECRET_MCP_DATABASE",
                    user_data_path("fatsecret-mcp-server") / "state.sqlite3",
                )
            ),
            timeout_seconds=float(os.getenv("FATSECRET_MCP_TIMEOUT", "30")),
            default_retry_after_seconds=int(
                os.getenv("FATSECRET_MCP_DEFAULT_RETRY_AFTER", "300")
            ),
            mutation_delay_seconds=float(
                os.getenv("FATSECRET_MCP_MUTATION_DELAY", "1")
            ),
            allow_credential_tools=_env_bool(
                "FATSECRET_MCP_ALLOW_CREDENTIAL_TOOLS", False
            ),
            telemetry_enabled=_env_bool("FATSECRET_MCP_TELEMETRY", True),
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")
