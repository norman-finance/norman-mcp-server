"""The OAuth state file is the only copy of every hosted session.

A record this SDK version cannot read must not take the rest of the state down
with it, and client records must survive rewrites with all their fields.
"""

import asyncio
import json
import time

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl

import norman_mcp.auth.provider as provider_module
from norman_mcp.auth.provider import NormanOAuthProvider

FUTURE = int(time.time()) + 86400


@pytest.fixture
def state_file(monkeypatch, tmp_path):
    path = tmp_path / "oauth_state.json"
    monkeypatch.setattr(provider_module, "_STATE_FILE", str(path))
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_ID", "upstream-client")
    monkeypatch.delenv("NORMAN_OAUTH_CLIENT_SECRET", raising=False)
    return path


def new_provider():
    return NormanOAuthProvider(AnyHttpUrl("https://mcp.example.invalid"))


def legacy_state():
    # Shape written by main (SDK 1.30), including the empty client_id that an
    # unauthenticated GET /authorize?client_id= used to auto-register.
    return {
        "clients": {
            "": {"client_id": "", "redirect_uris": ["http://localhost:6274/oauth/callback"]},
            "claude-client": {
                "client_id": "claude-client",
                "client_name": "Claude",
                "client_secret": None,
                "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "read write",
            },
        },
        "refresh_tokens": {
            "mcp_refresh_a": {"token": "mcp_refresh_a", "client_id": "claude-client", "scopes": ["read"], "expires_at": FUTURE},
        },
        "tokens": {
            "mcp_a": {"token": "mcp_a", "client_id": "claude-client", "scopes": ["read"], "expires_at": FUTURE},
        },
        "token_mapping": {"mcp_a": "norman_a", "refresh_for_mcp_a": "norman_refresh_a"},
        "token_to_company_id": {"mcp_a": "company-a"},
    }


def test_one_unreadable_client_does_not_drop_sessions_or_mappings(state_file):
    state_file.write_text(json.dumps(legacy_state()))

    provider = new_provider()

    assert "claude-client" in provider.clients
    assert "mcp_a" in provider.tokens and "mcp_refresh_a" in provider.refresh_tokens
    assert provider.get_norman_token("mcp_a") == "norman_a"
    assert provider.token_to_company_id == {"mcp_a": "company-a"}


def test_saving_after_a_partial_load_keeps_everything_on_disk(state_file):
    state_file.write_text(json.dumps(legacy_state()))
    provider = new_provider()

    provider._save_state()  # e.g. triggered by the next registration or login

    saved = json.loads(state_file.read_text())
    assert set(saved["clients"]) >= {"", "claude-client"}  # unreadable record kept verbatim
    assert saved["clients"][""] == legacy_state()["clients"][""]
    assert "mcp_a" in saved["tokens"] and "mcp_refresh_a" in saved["refresh_tokens"]
    assert saved["token_mapping"]["mcp_a"] == "norman_a"

    restarted = new_provider()
    assert restarted.get_norman_token("mcp_a") == "norman_a"


def test_unreadable_state_file_is_backed_up_before_it_can_be_replaced(state_file):
    state_file.write_text("{ not json")

    provider = new_provider()

    assert provider.tokens == {}
    backups = list(state_file.parent.glob("oauth_state.json.unreadable-*"))
    assert len(backups) == 1 and backups[0].read_text() == "{ not json"


def test_adding_a_redirect_uri_keeps_every_client_field(state_file):
    provider = new_provider()
    provider.clients["confidential"] = OAuthClientInformationFull(
        client_id="confidential",
        client_secret="server-issued-secret",
        client_id_issued_at=1_700_000_000,
        client_secret_expires_at=FUTURE,
        redirect_uris=["http://127.0.0.1:51000/callback"],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="read write",
        application_type="native",
    )

    provider.add_redirect_uri("confidential", "http://127.0.0.1:52000/callback")

    client = provider.clients["confidential"]
    assert [str(uri) for uri in client.redirect_uris] == [
        "http://127.0.0.1:51000/callback",
        "http://127.0.0.1:52000/callback",
    ]
    assert client.client_secret_expires_at == FUTURE
    assert client.client_id_issued_at == 1_700_000_000
    assert client.application_type == "native"


def test_registration_without_refresh_token_grant_can_still_refresh(state_file):
    provider = new_provider()
    client = OAuthClientInformationFull(
        client_id="auth-code-only",
        redirect_uris=["http://127.0.0.1:51000/callback"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code"],
        response_types=["code"],
        scope="read write",
        client_id_issued_at=1_700_000_000,
    )

    asyncio.run(provider.register_client(client))

    stored = provider.clients["auth-code-only"]
    assert stored.grant_types == ["authorization_code", "refresh_token"]
    assert stored.client_id_issued_at == 1_700_000_000
