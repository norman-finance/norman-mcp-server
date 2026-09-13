"""Exercise both refresh paths against a single-use upstream refresh token."""

import asyncio
import json
import threading
import time

import pytest
import requests
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import AccessToken, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import norman_mcp.auth.provider as provider_module
from norman_mcp.auth.provider import NormanOAuthProvider


def response(status, body):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    return result


class RotatingUpstream:
    def __init__(self):
        self.versions = {"a": 0, "b": 0}
        self.seen = []
        self.lock = threading.Lock()

    def post(self, url, data, **kwargs):
        assert url == "https://norman.example.invalid/token"
        with self.lock:
            token = data["refresh_token"]
            self.seen.append(token)
            for grant, version in self.versions.items():
                if token == f"refresh_{grant}_{version}":
                    self.versions[grant] += 1
                    return response(
                        200,
                        {
                            "access_token": f"access_{grant}_{version + 1}",
                            "refresh_token": f"refresh_{grant}_{version + 1}",
                        },
                    )
            return response(400, {"error": "invalid_grant"})


@pytest.fixture
def provider(monkeypatch, tmp_path):
    monkeypatch.setattr(provider_module, "_STATE_FILE", str(tmp_path / "oauth_state.json"))
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_ID", "upstream-client")
    monkeypatch.delenv("NORMAN_OAUTH_CLIENT_SECRET", raising=False)
    result = NormanOAuthProvider(AnyHttpUrl("https://mcp.example.invalid"))
    result.norman_token_url = "https://norman.example.invalid/token"
    result.clients["shared-client"] = OAuthClientInformationFull(
        client_id="shared-client",
        redirect_uris=["https://claude.ai/callback"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="read write",
    )
    for grant in ("a", "b"):
        access_key = f"mcp_{grant}"
        refresh_key = f"mcp_refresh_{grant}"
        result.tokens[access_key] = AccessToken(
            token=access_key,
            client_id="shared-client",
            scopes=["read", "write"],
            expires_at=int(time.time()) + 86400,
        )
        result.refresh_tokens[refresh_key] = RefreshToken(
            token=refresh_key,
            client_id="shared-client",
            scopes=["read", "write"],
            expires_at=int(time.time()) + 30 * 86400,
        )
        result.token_mapping.update(
            {
                access_key: f"access_{grant}_0",
                refresh_key: f"refresh_{grant}_0",
                f"refresh_for_{access_key}": f"refresh_{grant}_0",
            }
        )
        result.token_to_company_id[access_key] = f"company_{grant}"
    return result


@pytest.fixture
def upstream(monkeypatch):
    result = RotatingUpstream()
    monkeypatch.setattr(requests, "post", result.post)

    # Also isolate the old implementation's async transport for baseline runs.
    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            return await asyncio.to_thread(requests.post, url, **kwargs)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeAsyncClient)
    return result


def token_client(provider):
    handler = TokenHandler(provider, ClientAuthenticator(provider))
    app = Starlette(routes=[Route("/token", handler.handle, methods=["POST"])])
    return TestClient(app, raise_server_exceptions=False)


def refresh_request(client, grant="a"):
    return client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "shared-client",
            "refresh_token": f"mcp_refresh_{grant}",
        },
    )


def test_transparent_refresh_then_client_refresh_survives_restart(provider, upstream):
    assert provider.refresh_norman_token_sync("mcp_a") == "access_a_1"

    # The fix must survive a deploy using the existing persisted state format.
    restored = NormanOAuthProvider(AnyHttpUrl("https://mcp.example.invalid"))
    restored.norman_token_url = provider.norman_token_url
    with token_client(restored) as client:
        result = refresh_request(client)
    assert result.status_code == 200
    assert result.json()["refresh_token"] == "mcp_refresh_a"
    new_access = result.json()["access_token"]
    assert restored.get_norman_token(new_access) == "access_a_2"
    assert restored.get_norman_token("mcp_a") == "access_a_2"
    assert restored.token_mapping["mcp_refresh_a"] == "refresh_a_2"
    assert upstream.seen == ["refresh_a_0", "refresh_a_1"]
    assert restored.token_mapping["mcp_refresh_b"] == "refresh_b_0"
    assert restored.get_norman_token("mcp_b") == "access_b_0"
    assert restored.get_company_for_token("mcp_b") == "company_b"


def test_client_refresh_keeps_older_live_access_token_refreshable(provider, upstream):
    with token_client(provider) as client:
        result = refresh_request(client)
    assert result.status_code == 200
    new_access = result.json()["access_token"]

    assert provider.refresh_norman_token_sync("mcp_a") == "access_a_2"
    assert provider.refresh_norman_token_sync(new_access) == "access_a_3"
    assert provider.get_norman_token("mcp_a") == "access_a_3"
    assert provider.token_mapping["mcp_refresh_a"] == "refresh_a_3"
    assert upstream.seen == ["refresh_a_0", "refresh_a_1", "refresh_a_2"]


def test_concurrent_refresh_paths_share_a_grant_lock_without_blocking_other_users(
    provider, upstream, monkeypatch
):
    started = threading.Event()
    release = threading.Event()
    waiting = threading.Event()
    original_lock_for = provider._refresh_lock_for

    def observe_waiter(key):
        lock = original_lock_for(key)
        if key == "refresh_for_mcp_a":
            waiting.set()
        return lock

    monkeypatch.setattr(provider, "_refresh_lock_for", observe_waiter)

    def blocked_post(url, data, **kwargs):
        if data["refresh_token"] == "refresh_a_0":
            started.set()
            assert release.wait(5), "test did not release upstream refresh"
        return upstream.post(url, data, **kwargs)

    monkeypatch.setattr(requests, "post", blocked_post)

    async def run():
        client = provider.clients["shared-client"]
        pending = asyncio.create_task(
            provider.exchange_refresh_token(client, provider.refresh_tokens["mcp_refresh_a"], [])
        )
        follower = None
        try:
            assert await asyncio.to_thread(started.wait, 5)
            follower = asyncio.create_task(
                asyncio.to_thread(provider.refresh_norman_token_sync, "mcp_a")
            )
            assert await asyncio.to_thread(waiting.wait, 5)
            # Same client_id, different account: its refresh must proceed now.
            other = await asyncio.wait_for(
                provider.exchange_refresh_token(
                    client, provider.refresh_tokens["mcp_refresh_b"], []
                ),
                timeout=2,
            )
            assert provider.get_norman_token(other.access_token) == "access_b_1"
        finally:
            release.set()
            result = await pending
            if follower is not None:
                assert await follower == "access_a_1"
        assert provider.get_norman_token(result.access_token) == "access_a_1"

    asyncio.run(run())
    assert sorted(upstream.seen) == ["refresh_a_0", "refresh_b_0"]


def test_parallel_client_refreshes_both_succeed(provider, upstream):
    async def run():
        return await asyncio.gather(
            *(
                provider.exchange_refresh_token(
                    provider.clients["shared-client"], provider.refresh_tokens["mcp_refresh_a"], []
                )
                for _ in range(2)
            )
        )

    results = asyncio.run(run())
    assert len({r.access_token for r in results}) == 2
    assert upstream.seen == ["refresh_a_0", "refresh_a_1"]
    for result in results:
        assert provider.get_norman_token(result.access_token) == "access_a_2"
        assert provider.token_mapping[f"refresh_for_{result.access_token}"] == "refresh_a_2"


def test_refresh_without_rotation_keeps_existing_refresh_token(provider, upstream, monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: response(200, {"access_token": "access_a_1"})
    )
    assert provider.refresh_norman_token_sync("mcp_a") == "access_a_1"
    assert provider.token_mapping["mcp_refresh_a"] == "refresh_a_0"
    with token_client(provider) as client:
        assert refresh_request(client).status_code == 200


def test_revoked_grant_returns_oauth_error_instead_of_500(provider, upstream, monkeypatch):
    before = dict(provider.token_mapping)
    monkeypatch.setattr(requests, "post", lambda *a, **k: response(400, {"error": "invalid_grant"}))
    with token_client(provider) as client:
        result = refresh_request(client)
    assert result.status_code == 400
    assert result.json()["error"] == "invalid_grant"
    assert result.headers["cache-control"] == "no-store"
    assert provider.token_mapping == before


def test_missing_upstream_mapping_returns_oauth_error(provider, upstream):
    del provider.token_mapping["mcp_refresh_a"]
    with token_client(provider) as client:
        result = refresh_request(client)
    assert result.status_code == 400
    assert result.json()["error"] == "invalid_grant"
    assert upstream.seen == []


@pytest.mark.parametrize("failure", ["timeout", "rate_limit", "upstream_5xx"])
def test_transient_failure_preserves_credentials_for_retry(
    provider, upstream, monkeypatch, failure
):
    before = dict(provider.token_mapping)

    def failed_post(*args, **kwargs):
        if failure == "timeout":
            raise requests.Timeout("timeout with sensitive request context")
        return response(429 if failure == "rate_limit" else 502, {"error": "unavailable"})

    monkeypatch.setattr(requests, "post", failed_post)
    with token_client(provider) as client:
        result = refresh_request(client)
        assert result.status_code == 503
        assert result.headers["retry-after"] == "5"
        assert "sensitive" not in result.text
        assert provider.token_mapping == before
        monkeypatch.setattr(requests, "post", upstream.post)
        assert refresh_request(client).status_code == 200


@pytest.mark.parametrize(
    "body", [[], {}, {"access_token": 42}, {"access_token": "ok", "refresh_token": 42}]
)
def test_invalid_upstream_payload_never_overwrites_credentials(
    provider, upstream, monkeypatch, body
):
    before = dict(provider.token_mapping)
    monkeypatch.setattr(requests, "post", lambda *a, **k: response(200, body))
    with token_client(provider) as client:
        result = refresh_request(client)
    assert result.status_code == 502
    assert provider.token_mapping == before
