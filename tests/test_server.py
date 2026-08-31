from pathlib import Path

import pytest
from mcp import Client

from fatsecret_mcp_server.catalog import tools_for_profile
from fatsecret_mcp_server.server import create_server
from fatsecret_mcp_server.settings import Profile, Settings


@pytest.mark.parametrize(
    "profile",
    ["default", "member", "discovery", "diary", "bootstrap", "full"],
)
@pytest.mark.asyncio
async def test_server_advertises_only_profile_tools(
    profile: Profile, tmp_path: Path
) -> None:
    server = create_server(
        Settings(
            profile=profile,
            database_path=tmp_path / f"{profile}.sqlite3",
            telemetry_enabled=False,
        )
    )
    tools = await server.list_tools()
    expected = set(tools_for_profile(profile))
    expected.difference_update(
        {"set_credentials", "start_oauth_flow", "complete_oauth_flow"}
    )
    assert {tool.name for tool in tools} == expected


@pytest.mark.asyncio
async def test_credential_tool_requires_explicit_enablement(tmp_path: Path) -> None:
    server = create_server(
        Settings(
            profile="bootstrap",
            database_path=tmp_path / "credentials.sqlite3",
            telemetry_enabled=False,
            allow_credential_tools=True,
        )
    )
    names = {tool.name for tool in await server.list_tools()}
    assert {
        "set_credentials",
        "start_oauth_flow",
        "complete_oauth_flow",
    } <= names


@pytest.mark.asyncio
async def test_mutation_schemas_require_idempotency_keys(tmp_path: Path) -> None:
    server = create_server(
        Settings(
            profile="full",
            database_path=tmp_path / "state.sqlite3",
            telemetry_enabled=False,
            allow_credential_tools=True,
        )
    )
    tools = {tool.name: tool for tool in await server.list_tools()}

    for name in (
        "add_food_entry",
        "set_member_rdi",
        "create_member_recipe",
        "replace_member_recipe",
        "delete_member_recipe",
        "add_member_recipe_ingredient",
        "replace_member_recipe_ingredient",
        "delete_member_recipe_ingredient",
        "copy_member_recipe",
    ):
        assert "idempotency_key" in tools[name].input_schema["required"]


@pytest.mark.asyncio
async def test_ingredient_schema_uses_food_id_and_optional_portion(
    tmp_path: Path,
) -> None:
    server = create_server(
        Settings(
            profile="full",
            database_path=tmp_path / "state.sqlite3",
            telemetry_enabled=False,
            allow_credential_tools=True,
        )
    )
    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["add_member_recipe_ingredient"].input_schema

    assert "food_id" in schema["required"]
    assert "amount" in schema["required"]
    assert "portion_id" not in schema["required"]


@pytest.mark.asyncio
async def test_mcp_client_negotiates_and_lists_tools(tmp_path: Path) -> None:
    server = create_server(
        Settings(
            profile="discovery",
            database_path=tmp_path / "protocol.sqlite3",
            telemetry_enabled=False,
        )
    )

    async with Client(server) as client:
        result = await client.list_tools()

    assert {tool.name for tool in result.tools} == tools_for_profile("discovery")


@pytest.mark.asyncio
async def test_resolver_execution_is_profile_scoped(tmp_path: Path) -> None:
    server = create_server(
        Settings(
            profile="discovery",
            database_path=tmp_path / "resolver.sqlite3",
            telemetry_enabled=False,
        )
    )

    async with Client(server) as client:
        blocked = await client.call_tool(
            "resolve_fatsecret_capability",
            {"need": "profile.get", "execute": True},
        )
        sensitive = await client.call_tool(
            "resolve_fatsecret_capability", {"need": "profile.get_auth"}
        )

    assert blocked.is_error is True
    assert sensitive.structured_content == {"matches": []}


@pytest.mark.asyncio
async def test_tools_include_behavior_annotations(tmp_path: Path) -> None:
    server = create_server(
        Settings(
            profile="full",
            database_path=tmp_path / "annotations.sqlite3",
            telemetry_enabled=False,
            allow_credential_tools=True,
        )
    )
    tools = {tool.name: tool for tool in await server.list_tools()}

    read_annotations = tools["get_food"].annotations
    delete_annotations = tools["delete_member_recipe"].annotations
    resume_annotations = tools["resume_member_operation"].annotations
    assert read_annotations is not None
    assert delete_annotations is not None
    assert resume_annotations is not None
    assert read_annotations.read_only_hint is True
    assert delete_annotations.destructive_hint is True
    assert delete_annotations.idempotent_hint is True
    assert resume_annotations.idempotent_hint is True
