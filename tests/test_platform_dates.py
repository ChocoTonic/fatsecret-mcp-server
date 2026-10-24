"""Exercise epoch-day conversion through MCP and the real Platform serializer."""

from unittest.mock import Mock

import pytest
from fatsecret import Fatsecret
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
@pytest.mark.parametrize("day", [0, 20749, None])
async def test_platform_tools_preserve_epoch_day_on_wire(tmp_path, monkeypatch, day):
    runtime = execution(tmp_path)
    platform = Fatsecret("key", "secret", session_token=("token", "secret"))
    call = Mock(return_value={})
    monkeypatch.setattr(platform, "_call", call)
    monkeypatch.setattr(runtime, "official_client", lambda **kwargs: platform)
    server = create_server(runtime=runtime, settings=runtime.settings)
    async with Client(server) as client:
        for name, arguments in [
            ("get_user_food_entries", {"date": day}),
            ("get_weight_month", {"date": day}),
            (
                "add_food_entry",
                {
                    "date": day,
                    "food_id": 3451,
                    "food_entry_name": "Naan",
                    "serving_id": 52131,
                    "number_of_units": 76.69,
                    "meal": "lunch",
                    "idempotency_key": "epoch-day-regression",
                },
            ),
        ]:
            call.reset_mock()
            result = await client.call_tool(name, arguments)
            assert not result.is_error
            if name == "get_user_food_entries" and day is None:
                call.assert_not_called()
                continue
            params = call.call_args.args[0]
            if day is None:
                assert "date" not in params
            else:
                assert params["date"] == day
