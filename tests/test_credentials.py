import json

import pytest

from fatsecret_mcp_server.credentials import CredentialStore, OfficialCredentials


def test_oauth_pair_is_stored_as_one_keyring_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "fatsecret_mcp_server.credentials.keyring.set_password",
        lambda service, name, value: writes.append((service, name, value)),
    )
    store = CredentialStore()

    store.set_oauth_session("token", "secret")

    assert len(writes) == 1
    assert writes[0][1] == "oauth1_session"
    assert json.loads(writes[0][2]) == {
        "access_token": "token",
        "access_secret": "secret",
    }


def test_official_identity_is_stable_across_token_rotation() -> None:
    store = CredentialStore()
    first = OfficialCredentials("key", "secret", "account-42", "token-a", "a")
    second = OfficialCredentials("key", "secret", "account-42", "token-b", "b")

    assert store.account_identity("official", first) == store.account_identity(
        "official", second
    )
