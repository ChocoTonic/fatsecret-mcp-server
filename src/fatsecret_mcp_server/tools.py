"""Typed MCP tool handlers backed by the public FatSecret package."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from typing import Annotated, Any, Literal

from anyio import to_thread
from fatsecret import (
    WebIngredientWrite,
    WebMealType,
    WebRecipeCopyRequest,
    WebRecipeWrite,
)
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .capabilities import (
    executable_reads_for_profile,
    latest_capabilities,
    serialize,
)
from .catalog import POLICY_BY_NAME, tools_for_profile
from .runtime import Runtime
from .settings import Profile

Meal = Literal["breakfast", "lunch", "dinner", "other"]
PositiveId = Annotated[int, Field(gt=0)]
PositiveAmount = Annotated[float, Field(gt=0)]
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=255)]
Page = Annotated[int, Field(ge=0)]
Limit = Annotated[int, Field(ge=1, le=50)]
Calories = Annotated[int, Field(ge=1, le=100_000)]
RecipeTitle = Annotated[str, Field(min_length=1, max_length=255)]
RecipeDescription = Annotated[str, Field(min_length=1, max_length=2000)]
Directions = Annotated[list[str], Field(max_length=8)]


async def _thread(callback: Any, /, *args: Any, **kwargs: Any) -> Any:
    return await to_thread.run_sync(partial(callback, *args, **kwargs))


def register_tools(server: MCPServer, runtime: Runtime, profile: Profile) -> None:
    active = set(tools_for_profile(profile))
    if not runtime.settings.allow_credential_tools:
        active.difference_update(
            {"set_credentials", "start_oauth_flow", "complete_oauth_flow"}
        )

    def tool(name: str):
        def register(callback: Any) -> Any:
            if name in active:
                policy = POLICY_BY_NAME[name]
                server.tool(
                    name=name,
                    annotations=ToolAnnotations(
                        read_only_hint=not policy.mutating,
                        destructive_hint=name.startswith("delete_"),
                        idempotent_hint=policy.mutating,
                        open_world_hint=True,
                    ),
                )(callback)
            return callback

        return register

    @tool("set_credentials")
    async def set_credentials(
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        access_token: str | None = None,
        access_secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> dict[str, bool]:
        """Store provided FatSecret credentials in the operating-system keyring."""
        if not runtime.settings.allow_credential_tools:
            raise RuntimeError(
                "credential tools are disabled; configure environment variables or "
                "set FATSECRET_MCP_ALLOW_CREDENTIAL_TOOLS=true"
            )
        values = {
            "consumer_key": consumer_key,
            "consumer_secret": consumer_secret,
            "access_token": access_token,
            "access_secret": access_secret,
            "username": username,
            "password": password,
        }
        for name, value in values.items():
            if value is not None:
                runtime.credentials.set(name, value)
        return runtime.invoke("set_credentials", runtime.credentials.status)

    @tool("start_oauth_flow")
    async def start_oauth_flow(callback_url: str = "oob") -> dict[str, str]:
        """Start OAuth1 authorization and return the user-facing URL."""
        return await _thread(
            runtime.invoke,
            "start_oauth_flow",
            lambda: runtime.start_oauth(callback_url),
        )

    @tool("complete_oauth_flow")
    async def complete_oauth_flow(flow_id: str, verifier: str) -> dict[str, bool]:
        """Exchange an OAuth1 verifier and securely retain the user token."""
        return await _thread(
            runtime.invoke,
            "complete_oauth_flow",
            lambda: runtime.complete_oauth(flow_id, verifier),
        )

    @tool("authenticate_with_password")
    async def authenticate_with_password() -> dict[str, bool]:
        """Verify configured member-site credentials without accepting secrets."""

        def authenticate() -> dict[str, bool]:
            with runtime.web_client() as client:
                client.login()
            return {"member_authenticated": True}

        return await _thread(runtime.invoke, "authenticate_with_password", authenticate)

    @tool("check_auth_status")
    async def check_auth_status() -> dict[str, bool]:
        """Report which credential sets are configured without exposing values."""
        return runtime.invoke("check_auth_status", runtime.credentials.status)

    @tool("search_foods")
    async def search_foods(
        query: str,
        page: Page = 0,
        limit: Limit = 20,
        region: str | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search foods with the latest reviewed Platform endpoint."""

        def search() -> Any:
            return runtime.official_client().foods.search_v5(
                search_expression=query,
                page_number=page,
                max_results=limit,
                region=region,
                language=language,
            )

        return await _thread(runtime.invoke, "search_foods", search)

    @tool("get_food")
    async def get_food(food_id: PositiveId) -> dict[str, Any] | None:
        """Get one food by exact FatSecret food ID using the latest endpoint."""
        return await _thread(
            runtime.invoke,
            "get_food",
            lambda: runtime.official_client().foods.get_v5(food_id),
        )

    @tool("search_recipes")
    async def search_recipes(
        query: str,
        page: Page = 0,
        limit: Limit = 20,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search public recipes using the latest reviewed Platform endpoint."""
        return await _thread(
            runtime.invoke,
            "search_recipes",
            lambda: runtime.official_client().recipes.search_v3(
                search_expression=query,
                page_number=page,
                max_results=limit,
                region=region,
            ),
        )

    @tool("get_recipe")
    async def get_recipe(recipe_id: PositiveId) -> dict[str, Any] | None:
        """Get one public recipe by exact recipe ID."""
        return await _thread(
            runtime.invoke,
            "get_recipe",
            lambda: runtime.official_client().recipes.get_v2(recipe_id),
        )

    @tool("get_user_profile")
    async def get_user_profile() -> dict[str, Any] | None:
        """Get the authenticated Platform user's profile."""
        return await _thread(
            runtime.invoke,
            "get_user_profile",
            lambda: runtime.official_client(user_session=True).profile.get_v1(),
        )

    @tool("get_user_food_entries")
    async def get_user_food_entries(
        date: int | None = None, food_entry_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Get authenticated food diary entries by epoch-day or entry ID."""
        return await _thread(
            runtime.invoke,
            "get_user_food_entries",
            lambda: runtime.official_client(user_session=True).diary.entries_get_v2(
                date=date, food_entry_id=food_entry_id
            ),
        )

    @tool("add_food_entry")
    async def add_food_entry(
        food_id: PositiveId,
        food_entry_name: str,
        serving_id: PositiveId,
        number_of_units: PositiveAmount,
        meal: Meal,
        idempotency_key: IdempotencyKey,
        date: int | None = None,
    ) -> list[dict[str, Any]]:
        """Add a food diary entry once, keyed by a durable idempotency value."""
        payload = {
            "food_id": food_id,
            "food_entry_name": food_entry_name,
            "serving_id": serving_id,
            "number_of_units": number_of_units,
            "meal": meal,
            "date": date,
        }

        def create() -> Any:
            return runtime.idempotent_mutation(
                scope="food-entry:create",
                provider="official",
                key=idempotency_key,
                payload=payload,
                callback=lambda: runtime.official_client(
                    user_session=True
                ).diary.entry_create_v1(**payload),
            )

        return await _thread(runtime.invoke, "add_food_entry", create)

    @tool("get_weight_month")
    async def get_weight_month(date: int | None = None) -> list[dict[str, Any]]:
        """Get authenticated weight records for the month containing an epoch-day."""
        return await _thread(
            runtime.invoke,
            "get_weight_month",
            lambda: runtime.official_client(user_session=True).weight.get_month_v2(
                date=date
            ),
        )

    @tool("get_member_rdi")
    async def get_member_rdi() -> dict[str, Any]:
        """Get the RDI saved in the configured member account."""

        def get() -> Any:
            with runtime.web_client() as client:
                return client.get_rdi()

        return await _thread(runtime.invoke, "get_member_rdi", get)

    @tool("set_member_rdi")
    async def set_member_rdi(
        calories_per_day: Calories, idempotency_key: IdempotencyKey
    ) -> dict[str, Any]:
        """Replace and verify member RDI exactly once."""

        def replace() -> Any:
            def mutate() -> Any:
                with runtime.web_client() as client:
                    return client.set_rdi(calories_per_day)

            return runtime.idempotent_mutation(
                scope="rdi:replace",
                provider="member",
                key=idempotency_key,
                payload={"calories_per_day": calories_per_day},
                callback=mutate,
            )

        return await _thread(runtime.invoke, "set_member_rdi", replace)

    @tool("list_member_recipes")
    async def list_member_recipes() -> list[dict[str, Any]]:
        """List every recipe owned by the configured member account."""

        def list_all() -> Any:
            with runtime.web_client() as client:
                return client.list_recipes()

        return await _thread(runtime.invoke, "list_member_recipes", list_all)

    @tool("get_member_recipe")
    async def get_member_recipe(recipe_id: PositiveId) -> dict[str, Any]:
        """Get writable metadata and hydrated ingredients for an owned recipe."""

        def get() -> Any:
            with runtime.web_client() as client:
                return client.get_recipe(recipe_id)

        return await _thread(runtime.invoke, "get_member_recipe", get)

    def recipe_write(
        title: RecipeTitle,
        description: RecipeDescription,
        servings: PositiveAmount,
        prep_minutes: int,
        cook_minutes: int,
        meal_types: list[WebMealType],
        directions: Directions,
    ) -> WebRecipeWrite:
        return WebRecipeWrite(
            title=title,
            description=description,
            servings=Decimal(str(servings)),
            prep_minutes=prep_minutes,
            cook_minutes=cook_minutes,
            meal_types=meal_types,
            directions=directions,
        )

    @tool("create_member_recipe")
    async def create_member_recipe(
        title: RecipeTitle,
        description: RecipeDescription,
        servings: PositiveAmount,
        prep_minutes: int,
        cook_minutes: int,
        idempotency_key: IdempotencyKey,
        meal_types: list[WebMealType] | None = None,
        directions: Directions | None = None,
    ) -> dict[str, Any]:
        """Create and verify owned recipe metadata exactly once."""
        recipe = recipe_write(
            title,
            description,
            servings,
            prep_minutes,
            cook_minutes,
            meal_types or [],
            directions or [],
        )

        def create() -> Any:
            def mutate() -> Any:
                with runtime.web_client() as client:
                    return client.create_recipe(recipe)

            return runtime.idempotent_mutation(
                scope="member-recipe:create",
                provider="member",
                key=idempotency_key,
                payload=recipe.model_dump(mode="json"),
                callback=mutate,
            )

        return await _thread(runtime.invoke, "create_member_recipe", create)

    @tool("replace_member_recipe")
    async def replace_member_recipe(
        recipe_id: PositiveId,
        title: RecipeTitle,
        description: RecipeDescription,
        servings: PositiveAmount,
        prep_minutes: int,
        cook_minutes: int,
        idempotency_key: IdempotencyKey,
        meal_types: list[WebMealType] | None = None,
        directions: Directions | None = None,
    ) -> dict[str, Any]:
        """Replace recipe metadata and directions while preserving ingredients."""
        recipe = recipe_write(
            title,
            description,
            servings,
            prep_minutes,
            cook_minutes,
            meal_types or [],
            directions or [],
        )

        def replace() -> Any:
            def mutate() -> Any:
                with runtime.web_client() as client:
                    return client.replace_recipe(recipe_id, recipe)

            return runtime.idempotent_mutation(
                scope=f"member-recipe:{recipe_id}:replace",
                provider="member",
                key=idempotency_key,
                payload=recipe.model_dump(mode="json"),
                callback=mutate,
            )

        return await _thread(runtime.invoke, "replace_member_recipe", replace)

    @tool("delete_member_recipe")
    async def delete_member_recipe(
        recipe_id: PositiveId, idempotency_key: IdempotencyKey
    ) -> dict[str, Any]:
        """Delete an owned recipe and verify absence exactly once."""

        def delete() -> Any:
            def mutate() -> Any:
                with runtime.web_client() as client:
                    return client.delete_recipe(recipe_id)

            return runtime.idempotent_mutation(
                scope=f"member-recipe:{recipe_id}:delete",
                provider="member",
                key=idempotency_key,
                payload={"recipe_id": recipe_id},
                callback=mutate,
            )

        return await _thread(runtime.invoke, "delete_member_recipe", delete)

    @tool("list_member_food_portions")
    async def list_member_food_portions(
        recipe_id: PositiveId, food_id: PositiveId
    ) -> dict[str, Any]:
        """Resolve exact portion IDs for a known food ID in a destination recipe."""

        def portions() -> Any:
            with runtime.web_client() as client:
                return client.list_food_portions(recipe_id, food_id)

        return await _thread(runtime.invoke, "list_member_food_portions", portions)

    def ingredient_write(
        food_id: PositiveId, amount: PositiveAmount, portion_id: int | None
    ) -> WebIngredientWrite:
        return WebIngredientWrite(
            food_id=food_id,
            amount=Decimal(str(amount)),
            portion_id=portion_id,
        )

    @tool("add_member_recipe_ingredient")
    async def add_member_recipe_ingredient(
        recipe_id: PositiveId,
        food_id: PositiveId,
        amount: PositiveAmount,
        idempotency_key: IdempotencyKey,
        portion_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a known food ID as an ingredient; omitted portion means grams."""
        ingredient = ingredient_write(food_id, amount, portion_id)

        def add() -> Any:
            def mutate() -> Any:
                with runtime.web_client() as client:
                    return client.add_recipe_ingredient(recipe_id, ingredient)

            return runtime.idempotent_mutation(
                scope=f"member-recipe:{recipe_id}:ingredient:create",
                provider="member",
                key=idempotency_key,
                payload=ingredient.model_dump(mode="json"),
                callback=mutate,
            )

        return await _thread(runtime.invoke, "add_member_recipe_ingredient", add)

    @tool("replace_member_recipe_ingredient")
    async def replace_member_recipe_ingredient(
        recipe_id: PositiveId,
        entry_id: PositiveId,
        food_id: PositiveId,
        amount: PositiveAmount,
        idempotency_key: IdempotencyKey,
        portion_id: int | None = None,
    ) -> dict[str, Any]:
        """Replace an ingredient by entry ID using a known food and exact amount."""
        ingredient = ingredient_write(food_id, amount, portion_id)

        def replace() -> Any:
            def mutate() -> Any:
                with runtime.web_client() as client:
                    return client.replace_recipe_ingredient(
                        recipe_id, entry_id, ingredient
                    )

            return runtime.idempotent_mutation(
                scope=f"member-recipe:{recipe_id}:ingredient:{entry_id}:replace",
                provider="member",
                key=idempotency_key,
                payload=ingredient.model_dump(mode="json"),
                callback=mutate,
            )

        return await _thread(
            runtime.invoke, "replace_member_recipe_ingredient", replace
        )

    @tool("delete_member_recipe_ingredient")
    async def delete_member_recipe_ingredient(
        recipe_id: PositiveId,
        entry_id: PositiveId,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        """Delete an ingredient by entry ID and verify absence exactly once."""

        def delete() -> Any:
            def mutate() -> Any:
                with runtime.web_client() as client:
                    return {
                        "recipe_id": recipe_id,
                        "entry_id": entry_id,
                        "deleted": client.delete_recipe_ingredient(recipe_id, entry_id),
                    }

            return runtime.idempotent_mutation(
                scope=f"member-recipe:{recipe_id}:ingredient:{entry_id}:delete",
                provider="member",
                key=idempotency_key,
                payload={"recipe_id": recipe_id, "entry_id": entry_id},
                callback=mutate,
            )

        return await _thread(runtime.invoke, "delete_member_recipe_ingredient", delete)

    @tool("copy_member_recipe")
    async def copy_member_recipe(
        source_recipe_id: PositiveId,
        title: RecipeTitle,
        idempotency_key: IdempotencyKey,
        wait: bool = True,
    ) -> dict[str, Any]:
        """Start an idempotent recipe copy and optionally follow retry deadlines."""

        def copy() -> Any:
            request = WebRecipeCopyRequest(title=title)
            operation = runtime.start_copy(
                source_recipe_id, request.title, idempotency_key
            )
            return _follow_copy(runtime, operation.operation_id) if wait else operation

        return await _thread(runtime.invoke, "copy_member_recipe", copy)

    @tool("get_member_operation")
    async def get_member_operation(operation_id: str) -> dict[str, Any] | None:
        """Get durable status for a member recipe copy operation."""
        return await _thread(
            runtime.invoke,
            "get_member_operation",
            lambda: runtime.get_copy(operation_id),
        )

    @tool("resume_member_operation")
    async def resume_member_operation(
        operation_id: str, wait: bool = True
    ) -> dict[str, Any]:
        """Resume a recipe copy, honoring its complete server retry deadline."""

        def resume() -> Any:
            operation = runtime.resume_copy(operation_id)
            return _follow_copy(runtime, operation_id) if wait else operation

        return await _thread(runtime.invoke, "resume_member_operation", resume)

    @tool("resolve_fatsecret_capability")
    async def resolve_fatsecret_capability(
        need: str,
        execute: bool = False,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Find latest backend operations and optionally execute one safe read."""
        started = time.perf_counter()
        capabilities = latest_capabilities()
        executable = executable_reads_for_profile(profile)
        words = [word.casefold() for word in need.split() if word]
        matches = [
            capability
            for capability in capabilities.values()
            if all(
                word
                in " ".join(
                    (
                        capability.name,
                        capability.description,
                        *capability.parameters,
                    )
                ).casefold()
                for word in words
            )
        ]
        matches.sort(key=lambda item: (item.mutating, item.name))
        selected = [item.name for item in matches[:8]]
        response: dict[str, Any] = {
            "matches": [
                {
                    "name": item.name,
                    "backend_method": f"{item.resource}.{item.method}",
                    "version": item.version,
                    "description": item.description,
                    "parameters": item.parameters,
                    "mutating": item.mutating,
                    "executable": item.name in executable,
                }
                for item in matches[:8]
            ]
        }
        try:
            if execute:
                if len(matches) != 1:
                    raise ValueError(
                        "execution requires a query matching exactly one capability"
                    )
                capability = matches[0]
                if capability.name not in executable:
                    raise ValueError(
                        "resolver execution is read-only; use a reviewed mutation tool"
                    )
                client = runtime.official_client()
                resource = getattr(client, capability.resource)
                method = getattr(resource, capability.method)
                response["result"] = await _thread(method, **(arguments or {}))
                response["result"] = serialize(response["result"])
        except Exception:
            runtime.record_resolver(selected, started, "error")
            raise
        runtime.record_resolver(selected, started, "success")
        return response


def _follow_copy(runtime: Runtime, operation_id: str) -> Any:
    while True:
        operation = runtime.get_copy(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status != "waiting":
            return operation
        if operation.retry_after is None:
            raise RuntimeError("waiting copy operation has no retry deadline")
        delay = max(
            0.0,
            (operation.retry_after - datetime.now(UTC)).total_seconds(),
        )
        time.sleep(delay)
        runtime.resume_copy(operation_id)
