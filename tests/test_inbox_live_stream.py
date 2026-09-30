"""Exercise Inbox lease guards through SDK 2's actual subscription handler."""

import asyncio
import json
import time
from contextlib import asynccontextmanager, contextmanager

import pytest
from mcp import Client, MCPError
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus, ResourceUpdated
from starlette.testclient import TestClient

from norman_mcp import context
from norman_mcp.apps.inbox import register_inbox
from norman_mcp.apps.inbox_live import InboxLive, PinnedAPI, register_inbox_live
from norman_mcp.server import create_app, create_cors_app
from tests.test_legacy_client_compatibility import assert_results, requests_for

COMPANY = "company-compat-fixture"


class Provider:
    def __init__(self):
        self.tokens = {
            name: AccessToken(
                token=name, client_id="client-" + name, scopes=[], expires_at=int(time.time()) + 600
            )
            for name in ("alice", "bob")
        }
        self.count = 0
        self.denied = {}

    def get_norman_token(self, token):
        return "norman-" + token if token in self.tokens else None

    def get_company_for_token(self, token):
        return COMPANY

    async def verify_token(self, token):
        return self.tokens.get(token)


class OfflineAPI:
    company_id = COMPANY

    def __init__(self, provider, watch=None):
        self.provider = provider
        self.watch = watch

    def _make_request(self, method, url, **kwargs):
        assert method == "GET"
        return {"publicId": COMPANY, "name": "Compatibility Fixture", "isSme": False}

    async def arequest(self, method, url, **kwargs):
        assert method == "GET"
        if self.watch and self.watch.token in self.provider.denied:
            return {"error": "Unavailable", "status_code": self.provider.denied[self.watch.token]}
        if url.endswith("assistant/workflow-runs/"):
            return {"runs": []}
        if url.endswith("accounting/rule-executions/"):
            return {"results": [], "count": self.provider.count, "next": None}
        if url.endswith("assistant/approvals/"):
            return {"items": []}
        return self._make_request(method, url, **kwargs)


class CountingBus:
    """Observe cleanup through the public SubscriptionBus contract."""

    def __init__(self):
        self.delegate = InMemorySubscriptionBus()
        self.listeners = 0

    async def publish(self, event):
        await self.delegate.publish(event)

    def subscribe(self, listener):
        self.listeners += 1
        unsubscribe = self.delegate.subscribe(listener)
        stopped = False

        def stop():
            nonlocal stopped
            if not stopped:
                stopped = True
                self.listeners -= 1
                unsubscribe()

        return stop


@contextmanager
def caller(provider, name="alice"):
    marker = auth_context_var.set(AuthenticatedUser(provider.tokens[name]))
    try:
        yield
    finally:
        auth_context_var.reset(marker)


@pytest.fixture(autouse=True)
def isolate_context(monkeypatch):
    monkeypatch.setattr(context, "_api_client", context.get_api_client())
    monkeypatch.setattr(context, "oauth_provider", context.get_oauth_provider())


def fixture_server(monkeypatch):
    provider, bus = Provider(), CountingBus()
    api = OfflineAPI(provider)
    service = InboxLive(provider, bus)
    patch_pinned_source(monkeypatch)

    @asynccontextmanager
    async def lifespan(_):
        context.set_api_client(api)
        yield {"api": api}

    server = MCPServer("offline-inbox-live", subscriptions=bus, lifespan=lifespan)
    register_inbox(server)
    register_inbox_live(server, service)
    return provider, bus, service, server


def patch_pinned_source(monkeypatch):
    async def source(pinned, *args, **kwargs):
        return await OfflineAPI(pinned.provider, pinned.watch).arequest(*args, **kwargs)

    monkeypatch.setattr(PinnedAPI, "arequest", source)


async def open_watch(client, page=1):
    result = await client.call_tool("watch_norman_inbox", {"page": page})
    assert not result.is_error, result
    data = result.structured_content
    return data.get("result", data)["resourceUri"]


def test_native_stream_invalidation_refetch_and_cleanup(monkeypatch):
    provider, bus, service, server = fixture_server(monkeypatch)

    async def exercise():
        with caller(provider):
            async with Client(server) as client:
                uri = await open_watch(client)
                async with client.listen(resource_subscriptions=[uri]) as subscription:
                    assert subscription.honored.resource_subscriptions == [uri]
                    before = await client.read_resource(uri)
                    assert json.loads(before.contents[0].text)["summary"]["approvals"] == 0
                    provider.count = 2
                    await service.tick()
                    event = await asyncio.wait_for(anext(subscription), 1)
                    assert event == ResourceUpdated(uri=uri)
                    after = await client.read_resource(uri)
                    assert json.loads(after.contents[0].text)["summary"]["approvals"] == 2
                    await service.tick()  # asOf alone must not generate another event.
                    with pytest.raises(asyncio.TimeoutError):
                        await asyncio.wait_for(anext(subscription), 0.03)
        assert service.listeners == 0
        assert bus.listeners == 0

    asyncio.run(exercise())


def test_expiry_closes_only_its_stream_and_releases_sdk_listener(monkeypatch):
    provider, bus, service, server = fixture_server(monkeypatch)

    async def exercise():
        with caller(provider):
            async with Client(server) as client:
                short_uri, long_uri = await open_watch(client), await open_watch(client, 2)
                service.watches[short_uri].expires = time.time() + 0.1
                async with client.listen(resource_subscriptions=[short_uri]) as short:
                    async with client.listen(resource_subscriptions=[long_uri]) as long:
                        with pytest.raises(StopAsyncIteration):
                            await asyncio.wait_for(anext(short), 1)
                        assert service.listeners == bus.listeners == 1
                        assert service.watches[short_uri].listeners == 0
                        await bus.publish(ResourceUpdated(uri=long_uri))
                        assert await asyncio.wait_for(anext(long), 1) == ResourceUpdated(
                            uri=long_uri
                        )
                        with pytest.raises(MCPError):
                            await client.read_resource(short_uri)
        assert service.listeners == bus.listeners == 0

    asyncio.run(exercise())


def test_revocation_closes_its_grant_while_other_grant_stays_live(monkeypatch):
    provider, bus, service, server = fixture_server(monkeypatch)

    async def exercise():
        with caller(provider):
            async with Client(server) as client:
                alice_uri = await open_watch(client)
                with caller(provider, "bob"):
                    bob_uri = await open_watch(client)
                    async with client.listen(resource_subscriptions=[bob_uri]) as bob:
                        with caller(provider, "alice"):
                            async with client.listen(resource_subscriptions=[alice_uri]) as alice:
                                provider.tokens.pop("alice")
                                with pytest.raises(StopAsyncIteration):
                                    await asyncio.wait_for(anext(alice), 2)
                                assert service.listeners == bus.listeners == 1
                                await bus.publish(ResourceUpdated(uri=bob_uri))
                                assert await asyncio.wait_for(anext(bob), 1) == ResourceUpdated(
                                    uri=bob_uri
                                )
        assert service.listeners == bus.listeners == 0

    asyncio.run(exercise())


def test_foreign_grant_is_rejected_before_ack_and_cannot_read(monkeypatch):
    provider, bus, service, server = fixture_server(monkeypatch)

    async def exercise():
        with caller(provider):
            async with Client(server) as client:
                uri = await open_watch(client)
                with caller(provider, "bob"):
                    with pytest.raises(MCPError):
                        async with client.listen(resource_subscriptions=[uri]):
                            pytest.fail("foreign grant was acknowledged")
                    with pytest.raises(MCPError):
                        await client.read_resource(uri)
        assert service.listeners == bus.listeners == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("status", (401, 403))
def test_upstream_auth_failure_ends_only_its_grant_stream(monkeypatch, status):
    provider, bus, service, server = fixture_server(monkeypatch)

    async def exercise():
        with caller(provider):
            async with Client(server) as client:
                alice_uri = await open_watch(client)
                with caller(provider, "bob"):
                    bob_uri = await open_watch(client)
                    async with client.listen(resource_subscriptions=[bob_uri]) as bob:
                        with caller(provider, "alice"):
                            async with client.listen(resource_subscriptions=[alice_uri]) as alice:
                                provider.denied["alice"] = status
                                await service.tick()
                                with pytest.raises(StopAsyncIteration):
                                    await asyncio.wait_for(anext(alice), 2)
                                assert alice_uri not in service.watches
                                assert service.listeners == bus.listeners == 1
                                await bus.publish(ResourceUpdated(uri=bob_uri))
                                assert await asyncio.wait_for(anext(bob), 1) == ResourceUpdated(
                                    uri=bob_uri
                                )
        assert service.listeners == bus.listeners == 0

    asyncio.run(exercise())


def configure_http(monkeypatch, tmp_path):
    patch_pinned_source(monkeypatch)
    monkeypatch.setenv("NORMAN_MCP_INBOX_LIVE", "1")
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_ID", "")
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)
    monkeypatch.setattr(
        "norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "offline-oauth.json")
    )
    provider = Provider()
    api = OfflineAPI(provider)
    server = create_app(
        host="127.0.0.1",
        public_url="http://localhost:8000",
        transport="streamable-http",
        streamable_http_options={"stateless": True, "json_response": True},
    )
    service = server._inbox_live
    service.provider = provider
    server._token_verifier = provider

    @asynccontextmanager
    async def lifespan(_):
        context.set_api_client(api)
        yield {"api": api}

    server._lowlevel_server.lifespan = lifespan
    return provider, service, server


def test_modern_http_ack_and_expiry_completion_with_json_response_enabled(monkeypatch, tmp_path):
    provider, service, server = configure_http(monkeypatch, tmp_path)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer alice",
        "MCP-Protocol-Version": "2026-07-28",
    }
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    with TestClient(create_cors_app(server), base_url="http://localhost:8000") as client:
        opened = client.post(
            "/mcp",
            headers={**headers, "MCP-Method": "tools/call", "MCP-Name": "watch_norman_inbox"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "watch_norman_inbox", "arguments": {}, "_meta": meta},
            },
        )
        assert opened.status_code == 200, opened.text
        data = opened.json()["result"]["structuredContent"]
        uri = data.get("result", data)["resourceUri"]
        service.watches[uri].expires = time.time() + 0.1
        response = client.post(
            "/mcp",
            headers={**headers, "MCP-Method": "subscriptions/listen"},
            json={
                "jsonrpc": "2.0",
                "id": "listen-http",
                "method": "subscriptions/listen",
                "params": {"notifications": {"resourceSubscriptions": [uri]}, "_meta": meta},
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert frames[0]["method"] == "notifications/subscriptions/acknowledged"
    assert frames[0]["params"]["notifications"]["resourceSubscriptions"] == [uri]
    assert frames[-1]["result"]["resultType"] == "complete"
    assert frames[-1]["result"]["_meta"]["io.modelcontextprotocol/subscriptionId"] == "listen-http"
    assert service.listeners == 0


@pytest.mark.parametrize("version", ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"))
def test_opt_in_keeps_existing_legacy_wire_contracts(version, monkeypatch, tmp_path):
    _, _, server = configure_http(monkeypatch, tmp_path)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer alice",
        "MCP-Protocol-Version": version,
    }
    results = []
    with TestClient(create_cors_app(server), base_url="http://localhost:8000") as client:
        for request_id, (method, params) in enumerate(requests_for(version), 1):
            response = client.post(
                "/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            )
            assert response.status_code == 200, response.text
            wire = response.json()
            assert "error" not in wire, wire
            results.append(wire["result"])
            if method == "initialize":
                client.post(
                    "/mcp",
                    headers=headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )
    assert_results(version, results)
