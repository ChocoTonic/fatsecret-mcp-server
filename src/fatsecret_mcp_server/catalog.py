"""MCP exposure policy; endpoint contracts remain owned by the backend."""

from __future__ import annotations

from dataclasses import dataclass

from .settings import Profile


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    category: str
    profiles: frozenset[Profile]
    mutating: bool = False


_ALL: frozenset[Profile] = frozenset(
    {"default", "member", "discovery", "diary", "bootstrap", "full"}
)
_DEFAULT: frozenset[Profile] = frozenset({"default", "member", "full"})
_BOOTSTRAP: frozenset[Profile] = frozenset({"bootstrap", "full"})
_DISCOVERY: frozenset[Profile] = frozenset({"default", "member", "discovery", "full"})
_DIARY: frozenset[Profile] = frozenset({"default", "member", "diary", "full"})
_MEMBER: frozenset[Profile] = frozenset({"member", "full"})


TOOL_POLICIES = (
    ToolPolicy("set_credentials", "auth", _BOOTSTRAP, True),
    ToolPolicy("start_oauth_flow", "auth", _BOOTSTRAP, True),
    ToolPolicy("complete_oauth_flow", "auth", _BOOTSTRAP, True),
    ToolPolicy("authenticate_with_password", "auth", _BOOTSTRAP, True),
    ToolPolicy("check_auth_status", "auth", _ALL),
    ToolPolicy("search_foods", "food", _DISCOVERY),
    ToolPolicy("get_food", "food", _DISCOVERY),
    ToolPolicy("search_recipes", "recipe", _DISCOVERY),
    ToolPolicy("get_recipe", "recipe", _DISCOVERY),
    ToolPolicy("get_user_profile", "profile", _DEFAULT),
    ToolPolicy("get_user_food_entries", "diary", _DIARY),
    ToolPolicy("add_food_entry", "diary", _DIARY, True),
    ToolPolicy("get_weight_month", "weight", _DIARY),
    ToolPolicy("get_member_rdi", "rdi", _MEMBER),
    ToolPolicy("set_member_rdi", "rdi", _MEMBER, True),
    ToolPolicy("list_member_diary_entries", "member_diary", _MEMBER),
    ToolPolicy("get_member_diary_entry", "member_diary", _MEMBER),
    ToolPolicy("list_member_diary_item_portions", "member_diary", _MEMBER),
    ToolPolicy("add_member_diary_entry", "member_diary", _MEMBER, True),
    ToolPolicy("delete_member_diary_entry", "member_diary", _MEMBER, True),
    ToolPolicy("list_member_recipes", "member_recipe", _MEMBER),
    ToolPolicy("get_member_recipe", "member_recipe", _MEMBER),
    ToolPolicy("create_member_recipe", "member_recipe", _MEMBER, True),
    ToolPolicy("replace_member_recipe", "member_recipe", _MEMBER, True),
    ToolPolicy("delete_member_recipe", "member_recipe", _MEMBER, True),
    ToolPolicy("list_member_food_portions", "member_recipe", _MEMBER),
    ToolPolicy("add_member_recipe_ingredient", "member_recipe", _MEMBER, True),
    ToolPolicy("replace_member_recipe_ingredient", "member_recipe", _MEMBER, True),
    ToolPolicy("delete_member_recipe_ingredient", "member_recipe", _MEMBER, True),
    ToolPolicy("copy_member_recipe", "member_recipe", _MEMBER, True),
    ToolPolicy("get_member_operation", "member_recipe", _MEMBER),
    ToolPolicy("resume_member_operation", "member_recipe", _MEMBER, True),
    ToolPolicy("resolve_fatsecret_capability", "discovery", _ALL),
)

POLICY_BY_NAME = {policy.name: policy for policy in TOOL_POLICIES}


def tools_for_profile(profile: Profile) -> frozenset[str]:
    return frozenset(
        policy.name for policy in TOOL_POLICIES if profile in policy.profiles
    )
