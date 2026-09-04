from fatsecret_mcp_server.capabilities import (
    EXECUTABLE_READS,
    MEMBER_WEB_READS,
    latest_capabilities,
)


def test_latest_versions_are_selected() -> None:
    capabilities = latest_capabilities()
    assert capabilities["foods.get"].method == "get_v5"
    assert capabilities["foods.search"].method == "search_v5"
    assert capabilities["recipes.search"].method == "search_v3"
    assert capabilities["weight.get_month"].method == "get_month_v2"
    assert capabilities["member_web.list_diary_entries"].version == 1
    assert capabilities["member_web.list_diary_entries"].provider == "member"


def test_mutations_are_classified() -> None:
    capabilities = latest_capabilities()
    assert capabilities["diary.entry_create"].mutating is True
    assert capabilities["foods.get"].mutating is False
    assert capabilities["member_web.add_diary_entry"].mutating is True
    assert capabilities["member_web.list_diary_entries"].mutating is False


def test_only_explicitly_reviewed_reads_are_executable() -> None:
    capabilities = latest_capabilities()
    assert {
        name for name, capability in capabilities.items() if capability.executable
    } == set(EXECUTABLE_READS) | set(MEMBER_WEB_READS)
    assert all(
        capabilities[name].method == method for name, method in EXECUTABLE_READS.items()
    )
    assert capabilities["exercises.entries_commit_day"].executable is False


def test_sensitive_auth_operation_is_not_discoverable() -> None:
    assert "profile.get_auth" not in latest_capabilities()
