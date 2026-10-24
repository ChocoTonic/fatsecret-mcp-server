"""Exercise epoch-day conversion through MCP and the real Platform serializer."""

from unittest.mock import Mock

import pytest
from mcp import Client

from fatsecret_mcp_server.credentials import CredentialStore, OfficialCredentials
from fatsecret_mcp_server.runtime import Runtime
from fatsecret_mcp_server.server import create_server
from fatsecret_mcp_server.settings import Settings


class Credentials(CredentialStore):
    def official(self, *, require_session=False):
        return OfficialCredentials("key", "secret", "account", "token", "secret")


def execution(tmp_path):
    return Runtime(
        Settings(profile="full", database_path=tmp_path / "state.sqlite3"),
        credentials=Credentials(),
    )


@pytest.mark.asyncio
async def test_missing_account_label_is_actionable_without_attempting_write(
    tmp_path,
    monkeypatch,
):
    runtime = execution(tmp_path)
    monkeypatch.setattr(
        runtime.credentials,
        "official",
        lambda **kwargs: OfficialCredentials(
            "key", "secret", None, "token", "private-secret"
        ),
    )
    attempted = Mock()
    monkeypatch.setattr(runtime, "official_client", attempted)
    server = create_server(runtime=runtime, settings=runtime.settings)
    async with Client(server) as client:
        result = await client.call_tool(
            "add_food_entry",
            {
                "date": 20749,
                "food_id": 3451,
                "food_entry_name": "Naan",
                "serving_id": 52131,
                "number_of_units": 76.69,
                "meal": "lunch",
                "idempotency_key": "missing-account-label",
            },
        )
    assert result.is_error
    message = str(result.content)
    assert "FATSECRET_ACCOUNT_ID" in message
    assert "no write was attempted" in message
    assert "private-secret" not in message
    attempted.assert_not_called()


@pytest.mark.asyncio
async def test_unexpected_errors_remain_masked(tmp_path, monkeypatch):
    runtime = execution(tmp_path)

    def fail(**kwargs):
        raise RuntimeError("private-secret")

    monkeypatch.setattr(runtime, "official_client", fail)
    server = create_server(runtime=runtime, settings=runtime.settings)
    async with Client(server) as client:
        result = await client.call_tool(
            "get_user_food_entries",
            {"date": 20749},
        )
    assert result.is_error
    assert "private-secret" not in str(result.content)
