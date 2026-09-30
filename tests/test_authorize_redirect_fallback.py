"""/authorize without redirect_uri must still pass the server-level allow-list.

Open DCR stores whatever redirect URIs a client registers. RFC 6749 lets a client
with exactly one registered URI omit redirect_uri, and the SDK then falls back to
that registered URI. Before this fix the fallback skipped the allow-list, so a
self-registered client with https://attacker.example/steal received a signed-in
victim's authorization code (Norman's OAuth app skips the consent screen).

These tests drive the real /register and /authorize routes in-process.
"""

import base64
import hashlib
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

import norman_mcp.auth.provider as provider_module
import norman_mcp.context as context_module

BASE = "http://localhost:3001"
VERIFIER = "fixture-pkce-verifier-" + "v" * 40
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(provider_module, "_STATE_FILE", str(tmp_path / "oauth_state.json"))
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_ID", "upstream-client")
    monkeypatch.delenv("NORMAN_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("NORMAN_MCP_ALLOWED_REDIRECT_HOSTS", raising=False)
    # create_app replaces the process-wide provider and API client; put them back.
    monkeypatch.setattr(context_module, "oauth_provider", context_module.oauth_provider)
    monkeypatch.setattr(context_module, "_api_client", context_module._api_client)

    from norman_mcp.server import create_app, create_cors_app

    server = create_app(public_url=BASE, transport="streamable-http", streamable_http_options={"stateless": True})
    with TestClient(create_cors_app(server), base_url=BASE) as test_client:
        yield test_client


def register(client, redirect_uri):
    response = client.post(
        "/register",
        json={
            "client_name": "Redirect fallback test",
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "read write",
        },
    )
    # Registration stays open on purpose; the allow-list is enforced at /authorize.
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


def authorize_without_redirect_uri(client, client_id):
    return client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "state": "fixture-state",
            "scope": "read write",
        },
        follow_redirects=False,
    )


def test_omitted_redirect_uri_cannot_fall_back_to_a_disallowed_registration(client):
    client_id = register(client, "https://attacker.example/steal")

    response = authorize_without_redirect_uri(client, client_id)

    assert response.status_code == 400, response.text
    assert "attacker.example" not in response.headers.get("location", "")


def test_explicit_disallowed_redirect_uri_is_still_rejected(client):
    client_id = register(client, "https://attacker.example/steal")

    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://attacker.example/steal",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "state": "fixture-state",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400, response.text


def test_omitted_redirect_uri_still_works_for_an_allowed_registration(client):
    client_id = register(client, "https://claude.ai/api/mcp/auth_callback")

    response = authorize_without_redirect_uri(client, client_id)

    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    # The browser goes to Norman's login, never straight back to the client.
    assert location.path.endswith("/api/v1/oauth/authorize/")


def test_validator_applies_the_allow_list_to_the_single_registered_uri():
    import norman_mcp.server  # noqa: F401  (applies the monkeypatch on import)
    from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull

    validate = OAuthClientInformationFull.validate_redirect_uri

    class Registered:
        def __init__(self, *uris):
            self.redirect_uris = list(uris)

    with pytest.raises(InvalidRedirectUriError):
        validate(Registered("https://attacker.example/steal"), None)
    assert validate(Registered("https://claude.ai/api/mcp/auth_callback"), None) == (
        "https://claude.ai/api/mcp/auth_callback"
    )
    with pytest.raises(InvalidRedirectUriError):
        validate(Registered("https://claude.ai/a", "https://claude.ai/b"), None)


def test_registration_response_shows_the_refresh_grant_it_stores(client):
    response = client.post(
        "/register",
        json={
            "client_name": "Auth-code-only client",
            "redirect_uris": ["http://127.0.0.1:51000/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "scope": "read write",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["grant_types"] == ["authorization_code", "refresh_token"]
