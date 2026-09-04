from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from fatsecret import GeneralError, WebDiaryEntry, WebDiaryEntryWrite, WebDiaryMeal
from mcp import Client

from fatsecret_mcp_server.capabilities import serialize
from fatsecret_mcp_server.runtime import Runtime
from fatsecret_mcp_server.server import create_server
from fatsecret_mcp_server.settings import Settings


class FakeFoods:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _search(self, version: int):
        self.calls.append(f"search_v{version}")
        if version > 1:
            raise GeneralError(10, "Unknown method")
        return [{"food_id": 42, "food_name": "Pasta"}]

    def search_v5(self, **kwargs):
        return self._search(5)

    def search_v4(self, **kwargs):
        return self._search(4)

    def search_v3(self, **kwargs):
        return self._search(3)

    def search_v2(self, **kwargs):
        return self._search(2)

    def search_v1(self, **kwargs):
        return self._search(1)


class FakeWebClient:
    def __init__(self) -> None:
        self.added: WebDiaryEntryWrite | None = None

    def add_diary_entry(self, entry):
        self.added = entry
        return WebDiaryEntry(
            entry_id=501,
            item_id=entry.item_id,
            entry_name=entry.entry_name,
            amount=entry.amount,
            portion_id=0,
            portion_name="serving",
            meal=entry.meal,
            date=entry.date,
            edit_url="https://example.test/501",
        )


class FakeRuntime:
    def __init__(self, tmp_path) -> None:
        self.settings = Settings(
            profile="member",
            database_path=tmp_path / "state.sqlite3",
            telemetry_enabled=False,
        )
        self.foods = FakeFoods()
        self.web = FakeWebClient()

    def invoke(self, tool_name, callback):
        return serialize(callback())

    def official_client(self):
        return SimpleNamespace(foods=self.foods)

    def web_client(self):
        return nullcontext(self.web)

    def idempotent_mutation(self, **kwargs):
        return kwargs["callback"]()


@pytest.mark.asyncio
async def test_food_search_falls_back_and_caches_latest_compatible_version(tmp_path):
    runtime = FakeRuntime(tmp_path)
    server = create_server(runtime=cast(Runtime, runtime), settings=runtime.settings)

    async with Client(server) as client:
        first = await client.call_tool("search_foods", {"query": "pasta"})
        second = await client.call_tool("search_foods", {"query": "pasta"})

    assert first.is_error is False
    assert second.is_error is False
    assert runtime.foods.calls == [
        "search_v5",
        "search_v4",
        "search_v3",
        "search_v2",
        "search_v1",
        "search_v1",
    ]


@pytest.mark.asyncio
async def test_member_diary_tool_preserves_recipe_portion_zero(tmp_path):
    runtime = FakeRuntime(tmp_path)
    server = create_server(runtime=cast(Runtime, runtime), settings=runtime.settings)

    async with Client(server) as client:
        result = await client.call_tool(
            "add_member_diary_entry",
            {
                "item_id": 42,
                "entry_name": "Pasta",
                "amount": 259,
                "meal": WebDiaryMeal.DINNER.value,
                "date": 20699,
                "portion_id": 0,
                "idempotency_key": "member-diary-test-key",
            },
        )

    assert result.is_error is False
    added = runtime.web.added
    assert added is not None
    assert added.portion_id == 0
    assert added.amount == Decimal("259.0")
