from fatsecret_mcp_server.catalog import TOOL_POLICIES, tools_for_profile

EXPECTED = {
    "set_credentials",
    "start_oauth_flow",
    "complete_oauth_flow",
    "authenticate_with_password",
    "check_auth_status",
    "search_foods",
    "get_food",
    "search_recipes",
    "get_recipe",
    "get_user_profile",
    "get_user_food_entries",
    "add_food_entry",
    "get_weight_month",
    "get_member_rdi",
    "set_member_rdi",
    "list_member_diary_entries",
    "get_member_diary_entry",
    "list_member_diary_item_portions",
    "add_member_diary_entry",
    "delete_member_diary_entry",
    "list_member_recipes",
    "get_member_recipe",
    "create_member_recipe",
    "replace_member_recipe",
    "delete_member_recipe",
    "list_member_food_portions",
    "add_member_recipe_ingredient",
    "replace_member_recipe_ingredient",
    "delete_member_recipe_ingredient",
    "copy_member_recipe",
    "get_member_operation",
    "resume_member_operation",
    "resolve_fatsecret_capability",
}


def test_inventory_is_exact() -> None:
    assert {policy.name for policy in TOOL_POLICIES} == EXPECTED
    assert len(TOOL_POLICIES) == 33


def test_resolver_is_in_every_profile() -> None:
    for profile in (
        "default",
        "member",
        "discovery",
        "diary",
        "bootstrap",
        "full",
    ):
        assert "resolve_fatsecret_capability" in tools_for_profile(profile)


def test_full_profile_is_complete() -> None:
    assert tools_for_profile("full") == EXPECTED
