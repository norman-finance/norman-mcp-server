"""Real OAuth routes under SDK 2, with all Norman upstream traffic stubbed locally."""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import requests
from starlette.testclient import TestClient

from norman_mcp import context
from norman_mcp.context import Context
from norman_mcp.server import create_app, create_cors_app

BASE = "http://localhost:3001"
VERIFIER = "fixture-pkce-verifier-" + "x" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
)


@pytest.fixture
def oauth_server(monkeypatch, tmp_path):
    state_file = tmp_path / "oauth.json"
    monkeypatch.setattr("norman_mcp.auth.provider._STATE_FILE", str(state_file))
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_ID", "norman-upstream-fixture")
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_SECRET", "norman-upstream-fixture-secret")
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)
    previous_provider = context.get_oauth_provider()
    previous_client = context.get_api_client()
    previous_token = context.get_api_token()
    previous_company = context.get_api_company_id()
    context.set_api_token(None)
    context.set_api_company_id(None)
    upstream = []
    original_async_client = httpx.AsyncClient

    def exchange(request):
        assert request.url.path.endswith("/oauth/token/")
        data = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "norman-code-fixture"
        assert data["client_id"] == "norman-upstream-fixture"
        assert data["client_secret"] == "norman-upstream-fixture-secret"
        assert data["redirect_uri"] == BASE + "/oauth/callback"
        upstream.append(data)
        return httpx.Response(
            200,
            json={"access_token": "norman-access-before", "refresh_token": "norman-refresh-before"},
        )

    def async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(exchange)
        return original_async_client(*args, **kwargs)

    def refresh(url, *, data, timeout):
        assert url.endswith("/oauth/token/")
        assert data == {
            "grant_type": "refresh_token",
            "refresh_token": "norman-refresh-before",
            "client_id": "norman-upstream-fixture",
            "client_secret": "norman-upstream-fixture-secret",
        }
        upstream.append(data)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {"access_token": "norman-access-rotated", "refresh_token": "norman-refresh-rotated"}
        ).encode()
        return response

    monkeypatch.setattr("norman_mcp.auth.provider.httpx.AsyncClient", async_client)
    monkeypatch.setattr(requests, "post", refresh)

    def make(persisted=None):
        if persisted is not None:
            state_file.write_text(json.dumps(persisted))
        server = create_app(
            public_url=BASE,
            transport="streamable-http",
            streamable_http_options={"stateless": True},
        )

        @server.tool()
        async def oauth_identity_probe(ctx: Context) -> dict[str, str]:
            api = ctx.request_context.lifespan_context["api"]
            return {"company": api.company_id, "normanToken": api._resolve_norman_token()}

        return (
            TestClient(create_cors_app(server), base_url=BASE),
            context.get_oauth_provider(),
            upstream,
        )

    try:
        yield make
    finally:
        context.set_oauth_provider(previous_provider)
        context.set_api_client(previous_client)
        context.set_api_token(previous_token)
        context.set_api_company_id(previous_company)


def register(client, redirect, method="none"):
    response = client.post(
        "/register",
        json={
            "client_name": "Local OAuth fixture",
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": method,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "read",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def authorize(client, registration, redirect):
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": redirect,
            "scope": "read",
            "state": "client-state-fixture",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303), response.text
    upstream_query = parse_qs(urlsplit(response.headers["location"]).query)
    assert upstream_query["client_id"] == ["norman-upstream-fixture"]
    assert upstream_query["redirect_uri"] == [BASE + "/oauth/callback"]
    response = client.get(
        "/oauth/callback",
        params={"code": "norman-code-fixture", "state": upstream_query["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    destination = urlsplit(response.headers["location"])
    assert destination._replace(query="").geturl() == redirect
    query = parse_qs(destination.query)
    assert query["state"] == ["client-state-fixture"]
    return query["code"][0]


def code_payload(code, redirect, verifier=VERIFIER):
    return {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
        "code_verifier": verifier,
    }


def basic(registration, secret=None):
    value = registration["client_id"] + ":" + (secret or registration["client_secret"])
    return {"Authorization": "Basic " + base64.b64encode(value.encode()).decode()}


@pytest.mark.parametrize(
    ("redirect", "omit_client_id"),
    [
        ("http://127.0.0.1:49152/callback", False),
        ("https://claude.ai/oauth/callback", False),
        ("https://chatgpt.com/cb", True),
    ],
)
def test_public_pkce_metadata_code_exchange_and_refresh(oauth_server, redirect, omit_client_id):
    client, provider, upstream = oauth_server()
    with client:
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        assert metadata["authorization_endpoint"] == BASE + "/authorize"
        assert metadata["token_endpoint"] == BASE + "/token"
        assert metadata["registration_endpoint"] == BASE + "/register"
        assert metadata["code_challenge_methods_supported"] == ["S256"]
        assert {"none", "client_secret_basic"} <= set(
            metadata["token_endpoint_auth_methods_supported"]
        )
        protected = client.get("/.well-known/oauth-protected-resource")
        assert protected.status_code == 200
        assert protected.json()["authorization_servers"] == [BASE + "/"]
        registration = register(client, redirect)
        assert not registration.get("client_secret")
        code = authorize(client, registration, redirect)
        payload = code_payload(code, redirect)
        if not omit_client_id:
            payload["client_id"] = registration["client_id"]
        # Both standard clients and the omitted-client-id fallback retain PKCE.
        response = client.post("/token", data=payload)
        assert response.status_code == 200, response.text
        tokens = response.json()
        assert tokens["scope"] == "read"
        assert response.headers["cache-control"] == "no-store"
        assert provider.get_norman_token(tokens["access_token"]) == "norman-access-before"
        replay = client.post(
            "/token", data={**code_payload(code, redirect), "client_id": registration["client_id"]}
        )
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"
        payload = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
        if not omit_client_id:
            payload["client_id"] = registration["client_id"]
        refreshed = client.post("/token", data=payload)
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["access_token"] != tokens["access_token"]
        assert (
            provider.get_norman_token(refreshed.json()["access_token"]) == "norman-access-rotated"
        )
        assert [item["grant_type"] for item in upstream] == ["authorization_code", "refresh_token"]


def test_wrong_pkce_verifier_is_rejected_without_consuming_code(oauth_server):
    client, provider, upstream = oauth_server()
    redirect = "http://localhost:49337/callback"
    with client:
        registration = register(client, redirect)
        code = authorize(client, registration, redirect)
        response = client.post("/token", data=code_payload(code, redirect, "wrong-verifier"))
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"
        assert "code_verifier" in response.json()["error_description"]
        assert code in provider.auth_codes
        assert provider.tokens == {}
        assert len(upstream) == 1
        assert client.post("/token", data=code_payload(code, redirect)).status_code == 200


def test_confidential_basic_client_exchange_refresh_and_bad_secret(oauth_server):
    client, provider, upstream = oauth_server()
    redirect = "http://localhost:49153/callback"
    with client:
        registration = register(client, redirect, "client_secret_basic")
        assert registration["client_secret"]
        code = authorize(client, registration, redirect)
        rejected = client.post(
            "/token", data=code_payload(code, redirect), headers=basic(registration, "wrong-secret")
        )
        assert rejected.status_code == 401
        assert rejected.json()["error"] == "invalid_client"
        assert code in provider.auth_codes
        response = client.post(
            "/token", data=code_payload(code, redirect), headers=basic(registration)
        )
        assert response.status_code == 200, response.text
        tokens = response.json()
        response = client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
            headers=basic(registration),
        )
        assert response.status_code == 200, response.text
        assert provider.get_norman_token(response.json()["access_token"]) == "norman-access-rotated"
        assert len(upstream) == 2


def test_pre_sdk2_persisted_client_and_tokens_still_work(oauth_server):
    expires = int(time.time()) + 3600
    persisted = {
        "clients": {
            "legacy-client": {
                "client_id": "legacy-client",
                "client_name": "Saved public client",
                "client_secret": "stale-public-client-secret",
                "redirect_uris": ["http://127.0.0.1:49152/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "read",
            }
        },
        "tokens": {
            "mcp_saved_access": {
                "token": "mcp_saved_access",
                "client_id": "legacy-client",
                "scopes": ["read"],
                "expires_at": expires,
            }
        },
        "refresh_tokens": {
            "mcp_saved_refresh": {
                "token": "mcp_saved_refresh",
                "client_id": "legacy-client",
                "scopes": ["read"],
                "expires_at": expires,
            }
        },
        "token_mapping": {
            "mcp_saved_access": "norman-access-before",
            "mcp_saved_refresh": "norman-refresh-before",
            "refresh_for_mcp_saved_access": "norman-refresh-before",
        },
        "token_to_company_id": {"mcp_saved_access": "saved-company"},
    }
    client, provider, upstream = oauth_server(persisted)
    with client:
        assert provider.clients["legacy-client"].client_secret is None
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer mcp_saved_access",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "oauth_identity_probe", "arguments": {}},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["structuredContent"] == {
            "company": "saved-company",
            "normanToken": "norman-access-before",
        }
        response = client.post(
            "/token", data={"grant_type": "refresh_token", "refresh_token": "mcp_saved_refresh"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["refresh_token"] == "mcp_saved_refresh"
        assert provider.get_norman_token(response.json()["access_token"]) == "norman-access-rotated"
        assert len(upstream) == 1
