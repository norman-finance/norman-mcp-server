"""Redirect-URI allow-list tests (OAuth authorization-code phishing defense)."""

import asyncio
import json

import pytest

from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.provider import RegistrationError
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull
from starlette.requests import Request

from norman_mcp.auth.provider import NormanOAuthProvider
from norman_mcp.security.redirects import is_allowed_redirect_uri


def test_rejects_external_https():
    # The reported attack: attacker-controlled HTTPS exfiltration target.
    assert is_allowed_redirect_uri("https://attacker.com/steal") is False
    assert is_allowed_redirect_uri("https://norman.finance.attacker.com/cb") is False
    assert is_allowed_redirect_uri("https://connect.smithery.ai.attacker.com/auth") is False


def test_allows_known_connector_https_hosts():
    assert is_allowed_redirect_uri("https://chatgpt.com/connector_platform_oauth_redirect")
    assert is_allowed_redirect_uri("https://claude.ai/api/mcp/auth_callback")
    assert is_allowed_redirect_uri(
        "https://connect.smithery.ai/smithery-deployments/deployment-id/auth"
    )
    # Subdomain of an allow-listed base domain.
    assert is_allowed_redirect_uri("https://mcp.norman.finance/oauth/callback")


def test_allows_http_loopback_any_port():
    assert is_allowed_redirect_uri("http://localhost:6274/oauth/callback")
    assert is_allowed_redirect_uri("http://127.0.0.1:51763/callback")
    assert is_allowed_redirect_uri("http://[::1]:6274/cb")


def test_rejects_plain_http_to_remote_host():
    assert is_allowed_redirect_uri("http://attacker.com/steal") is False


def test_allows_custom_native_scheme():
    assert is_allowed_redirect_uri("cursor://anysphere.cursor/callback")


def test_env_extension_adds_hosts(monkeypatch):
    monkeypatch.setenv("NORMAN_MCP_ALLOWED_REDIRECT_HOSTS", "partner.example, other.test")
    assert is_allowed_redirect_uri("https://partner.example/cb")
    assert is_allowed_redirect_uri("https://api.partner.example/cb")
    assert is_allowed_redirect_uri("https://other.test/cb")


def test_empty_or_garbage_rejected():
    assert is_allowed_redirect_uri("") is False
    assert is_allowed_redirect_uri("not a url") is False


def test_sdk_validate_patch_enforces_allowlist():
    """Importing the server monkeypatches the SDK validator to the allow-list.

    Critically, this rejects a disallowed URI even when the client has it in its
    own registered redirect_uris (open DCR lets an attacker self-register it).
    """
    import norman_mcp.server  # noqa: F401  (applies the monkeypatch on import)
    from mcp.shared.auth import OAuthClientInformationFull, InvalidRedirectUriError

    fn = OAuthClientInformationFull.validate_redirect_uri

    class _DummyClient:
        # Even though the attacker "registered" attacker.com, it must be rejected.
        redirect_uris = ["https://attacker.com/steal"]

    with pytest.raises(InvalidRedirectUriError):
        fn(_DummyClient(), "https://attacker.com/steal")

    assert fn(_DummyClient(), "https://chatgpt.com/cb") == "https://chatgpt.com/cb"


def _provider_without_external_state() -> NormanOAuthProvider:
    provider = object.__new__(NormanOAuthProvider)
    provider.clients = {}
    provider._save_state = lambda: None
    return provider


async def _register_request(handler: RegistrationHandler, redirect_uri: str):
    body = json.dumps(
        {
            "client_name": "Connector test client",
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "read",
        }
    ).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/register",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )
    return await handler.handle(request)


def _registration_handler() -> RegistrationHandler:
    return RegistrationHandler(
        provider=_provider_without_external_state(),
        options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["read"],
            default_scopes=["read"],
        ),
    )


def test_dcr_handler_registers_dynamic_smithery_callback():
    handler = _registration_handler()

    response = asyncio.run(
        _register_request(
            handler,
            "https://connect.smithery.ai/smithery-deployments/deployment-id/auth",
        )
    )

    assert response.status_code == 201
    response_body = json.loads(response.body)
    assert response_body["redirect_uris"] == [
        "https://connect.smithery.ai/smithery-deployments/deployment-id/auth"
    ]
    assert response_body["client_id"] in handler.provider.clients


def test_dcr_handler_returns_oauth_error_for_disallowed_redirect():
    handler = _registration_handler()

    response = asyncio.run(_register_request(handler, "https://attacker.com/steal"))

    assert response.status_code == 400
    assert json.loads(response.body) == {
        "error": "invalid_redirect_uri",
        "error_description": "One or more redirect_uris are not allowed",
    }
    assert handler.provider.clients == {}


def test_dcr_rejects_entire_registration_when_one_redirect_is_disallowed():
    provider = _provider_without_external_state()
    client_info = OAuthClientInformationFull(
        client_id="mixed-redirect-client",
        client_secret=None,
        redirect_uris=[
            "https://connect.smithery.ai/smithery-deployments/deployment-id/auth",
            "https://attacker.com/steal",
        ],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="read",
    )

    with pytest.raises(RegistrationError) as exc_info:
        asyncio.run(provider.register_client(client_info))

    assert exc_info.value.error == "invalid_redirect_uri"
    assert provider.clients == {}
