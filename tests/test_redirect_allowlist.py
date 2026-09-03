"""Dynamic OAuth redirect registration and exact-match tests."""

import asyncio

import pytest
from mcp.server.auth.provider import RegistrationError
from mcp.shared.auth import OAuthClientInformationFull

from norman_mcp.auth.provider import NormanOAuthProvider
from norman_mcp.security.redirects import is_allowed_redirect_uri


def test_allows_dynamic_https_callbacks_without_vendor_list():
    assert is_allowed_redirect_uri("https://new-client.example/oauth/callback")
    assert is_allowed_redirect_uri("https://chatgpt.com/connector_platform_oauth_redirect")
    assert is_allowed_redirect_uri("https://claude.ai/api/mcp/auth_callback")
    assert is_allowed_redirect_uri("https://www.perplexity.ai/rest/connections/oauth_callback")
    assert is_allowed_redirect_uri("https://vertexaisearch.cloud.google.com/oauth-redirect")


def test_allows_http_loopback_any_port():
    assert is_allowed_redirect_uri("http://localhost:6274/oauth/callback")
    assert is_allowed_redirect_uri("http://127.0.0.1:51763/callback")
    assert is_allowed_redirect_uri("http://[::1]:6274/cb")


def test_rejects_plain_http_to_remote_host():
    assert is_allowed_redirect_uri("http://remote.example/callback") is False


def test_allows_custom_native_scheme():
    assert is_allowed_redirect_uri("cursor://anysphere.cursor/callback")


def test_empty_or_garbage_rejected():
    assert is_allowed_redirect_uri("") is False
    assert is_allowed_redirect_uri("not a url") is False


def test_sdk_requires_exact_registered_redirect_uri():
    """Authorization cannot swap the redirect URI after registration."""
    from mcp.shared.auth import InvalidRedirectUriError

    fn = OAuthClientInformationFull.validate_redirect_uri

    class _DummyClient:
        redirect_uris = ["https://client.example/oauth/callback"]

    with pytest.raises(InvalidRedirectUriError):
        fn(_DummyClient(), "https://attacker.example/steal")

    assert fn(_DummyClient(), "https://client.example/oauth/callback") == (
        "https://client.example/oauth/callback"
    )


def test_dcr_accepts_dynamic_https_redirect_and_persists_client():
    provider = object.__new__(NormanOAuthProvider)
    provider.clients = {}
    provider._save_state = lambda: None
    client = OAuthClientInformationFull(
        client_id="dynamic-client",
        redirect_uris=["https://new-client.example/oauth/callback"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )

    asyncio.run(provider.register_client(client))

    assert provider.clients["dynamic-client"].redirect_uris == client.redirect_uris


def test_dcr_rejects_remote_http_redirect_without_persisting_client():
    provider = object.__new__(NormanOAuthProvider)
    provider.clients = {}
    provider._save_state = lambda: None
    client = OAuthClientInformationFull(
        client_id="insecure-client",
        redirect_uris=["http://remote.example/callback"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )

    with pytest.raises(RegistrationError) as exc_info:
        asyncio.run(provider.register_client(client))

    assert exc_info.value.error == "invalid_redirect_uri"
    assert provider.clients == {}
