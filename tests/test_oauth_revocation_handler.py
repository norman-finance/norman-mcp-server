"""SDK revocation handlers receive token records, not token strings.

The real handler is mounted only in this isolated test app. Norman's production
AuthSettings continues to leave the HTTP revocation endpoint disabled.
"""

import asyncio
import time

import pytest
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import AccessToken, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from norman_mcp.auth.provider import NormanOAuthProvider


@pytest.fixture(params=[True, False], ids=["tracked-grants", "legacy-aliases"])
def revocation_provider(monkeypatch, tmp_path, request):
    monkeypatch.setattr("norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "oauth.json"))
    monkeypatch.delenv("NORMAN_OAUTH_CLIENT_ID", raising=False)
    provider = NormanOAuthProvider(AnyHttpUrl("https://mcp.example.invalid"))
    for client_id in ("shared-client", "foreign-client"):
        provider.clients[client_id] = OAuthClientInformationFull(
            client_id=client_id,
            redirect_uris=["https://chatgpt.com/cb"],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )
    expires = int(time.time()) + 3600
    for grant, accesses in (("a", ["access_a", "access_a_previous"]), ("b", ["access_b"])):
        refresh = f"refresh_{grant}"
        provider.refresh_tokens[refresh] = RefreshToken(
            token=refresh, client_id="shared-client", scopes=["read"], expires_at=expires
        )
        provider.token_mapping[refresh] = f"norman_refresh_{grant}"
        for access in accesses:
            provider.tokens[access] = AccessToken(
                token=access, client_id="shared-client", scopes=["read"], expires_at=expires
            )
            provider.token_mapping[access] = f"norman_access_{grant}"
            provider.token_mapping[f"refresh_for_{access}"] = f"norman_refresh_{grant}"
            provider.token_to_company_id[access] = f"company_{grant}"
        if request.param:
            provider.token_grants.update({key: f"grant_{grant}" for key in [refresh, *accesses]})
    return provider


def handler_client(provider):
    handler = RevocationHandler(provider, ClientAuthenticator(provider))
    return TestClient(Starlette(routes=[Route("/revoke", handler.handle, methods=["POST"])]))


def revoke_payload(token, client_id="shared-client", hint="refresh_token"):
    # SDK 2.2's nullable client_secret field is required by its request model.
    # An explicit empty value isolates the provider's native-token contract.
    return {
        "client_id": client_id,
        "client_secret": "",
        "token": token,
        "token_type_hint": hint,
    }


def snapshot(provider):
    return {
        "tokens": {key: value.model_dump() for key, value in provider.tokens.items()},
        "refresh_tokens": {
            key: value.model_dump() for key, value in provider.refresh_tokens.items()
        },
        "mappings": dict(provider.token_mapping),
        "companies": dict(provider.token_to_company_id),
        "grants": dict(provider.token_grants),
        "clients": {key: value.model_dump() for key, value in provider.clients.items()},
    }


def assert_grant_a_removed_and_grant_b_preserved(provider, before):
    for access in ("access_a", "access_a_previous"):
        assert access not in provider.tokens
        assert access not in provider.token_mapping
        assert f"refresh_for_{access}" not in provider.token_mapping
        assert access not in provider.token_to_company_id
        assert access not in provider.token_grants
    assert "refresh_a" not in provider.refresh_tokens
    assert "refresh_a" not in provider.token_mapping
    assert "refresh_a" not in provider.token_grants
    after = snapshot(provider)
    assert after["tokens"] == {"access_b": before["tokens"]["access_b"]}
    assert after["refresh_tokens"] == {"refresh_b": before["refresh_tokens"]["refresh_b"]}
    assert after["mappings"] == {
        key: before["mappings"][key] for key in ("access_b", "refresh_for_access_b", "refresh_b")
    }
    assert after["companies"] == {"access_b": "company_b"}
    assert after["grants"] == {
        key: value for key, value in before["grants"].items() if key in ("access_b", "refresh_b")
    }
    assert after["clients"] == before["clients"]


@pytest.mark.parametrize(
    ("token", "hint"), [("access_a", "access_token"), ("refresh_a", "refresh_token")]
)
def test_sdk_handler_revokes_native_owned_token_and_all_grant_aliases(
    revocation_provider, token, hint
):
    before = snapshot(revocation_provider)
    with handler_client(revocation_provider) as client:
        response = client.post("/revoke", data=revoke_payload(token, hint=hint))
        assert response.status_code == 200, response.text
        assert response.content == b""
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
        # A retry remains a successful no-op after the whole family is gone.
        assert client.post("/revoke", data=revoke_payload(token, hint=hint)).status_code == 200
    assert_grant_a_removed_and_grant_b_preserved(revocation_provider, before)


@pytest.mark.parametrize(
    ("token", "hint"), [("access_a", "access_token"), ("refresh_a", "refresh_token")]
)
def test_sdk_handler_rejects_foreign_client_ownership_without_mutation(
    revocation_provider, token, hint
):
    before = snapshot(revocation_provider)
    with handler_client(revocation_provider) as client:
        response = client.post(
            "/revoke", data=revoke_payload(token, client_id="foreign-client", hint=hint)
        )
    # RFC 7009 does not reveal token existence to a different registered client.
    assert response.status_code == 200
    assert snapshot(revocation_provider) == before


def test_legacy_string_and_hint_callers_remain_supported(revocation_provider):
    before = snapshot(revocation_provider)
    asyncio.run(revocation_provider.revoke_token("refresh_a", "refresh_token"))
    assert_grant_a_removed_and_grant_b_preserved(revocation_provider, before)
