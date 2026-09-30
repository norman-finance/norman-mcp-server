"""Grant/company isolation, invalidations, and bounded Inbox observer state."""

import asyncio
import time
from types import SimpleNamespace

import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.subscriptions import InMemorySubscriptionBus
from mcp.shared.exceptions import MCPError

from norman_mcp.apps import inbox_live
from norman_mcp.apps.inbox_live import InboxLive, PinnedAPI, fingerprint


class Provider:
    def __init__(self):
        self.tokens = {
            token: AccessToken(
                token=token, client_id="client", scopes=[], expires_at=int(time.time()) + 3600
            )
            for token in ("alice", "bob")
        }
        self.mapping = {"alice": "norman-alice", "bob": "norman-bob"}
        self.companies = {"alice": "company-a", "bob": "company-a"}

    def get_norman_token(self, token):
        return self.mapping.get(token)

    def refresh_norman_token_sync(self, token):
        return None  # tests that need a refresh set their own

    def get_company_for_token(self, token):
        return self.companies.get(token)


class API:
    company_id = "company-a"

    def __init__(self):
        self.count = 1
        self.status = None
        self.calls = []

    async def arequest(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert method == "GET"
        if self.status:
            return {"error": "Unavailable", "status_code": self.status}
        if url.endswith("workflow-runs/"):
            return {"runs": []}
        if url.endswith("rule-executions/"):
            return {"count": self.count, "results": [], "next": None}
        return {"items": []}


@pytest.fixture
def setup(monkeypatch):
    provider = Provider()
    current = [provider.tokens["alice"]]
    monkeypatch.setattr(inbox_live, "get_access_token", lambda: current[0])
    service = InboxLive(provider, InMemorySubscriptionBus())
    api = API()

    async def source(self, *args, **kwargs):
        return await api.arequest(*args, **kwargs)

    monkeypatch.setattr(PinnedAPI, "arequest", source)
    return service, provider, current, api


@pytest.mark.asyncio
async def test_lease_is_opaque_idempotent_bounded_and_expires_with_grant(setup, monkeypatch):
    service, provider, current, api = setup
    provider.tokens["alice"].expires_at = int(time.time()) + 60
    opened = await service.open(api, 2)
    assert "alice" not in opened["resourceUri"] and "company-a" not in opened["resourceUri"]
    assert opened["expiresAt"] == provider.tokens["alice"].expires_at
    assert opened["page"] == 2
    assert await service.open(api, 2) == opened
    assert len(service.watches) == 1 and len(api.calls) == 3
    monkeypatch.setattr(inbox_live, "MAX_PER_GRANT", 1)
    with pytest.raises(ToolError, match="limit"):
        await service.open(api, 3)
    current[0] = provider.tokens["bob"]
    monkeypatch.setattr(inbox_live, "MAX_WATCHES", 1)
    with pytest.raises(ToolError, match="limit"):
        await service.open(api, 2)
    watch = service.watches[opened["resourceUri"]]
    watch.expires = time.time() - 1
    service.prune()
    assert not service.watches


@pytest.mark.asyncio
async def test_read_and_listen_share_uniform_grant_company_authorization(setup):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]
    assert '"companyId": "company-a"' in await service.read(uri, api)

    async def unexpected(_):
        raise AssertionError("Denied listen must not reach SDK acknowledgment")

    ctx = SimpleNamespace(
        method="subscriptions/listen",
        params={"notifications": {"resourceSubscriptions": [uri]}},
        lifespan_context={"api": api},
    )
    current[0] = provider.tokens["bob"]  # Same company, different authenticated grant.
    for bad_uri in (uri, inbox_live.PREFIX + "missing"):
        with pytest.raises(MCPError, match=inbox_live.DENIED):
            await service.read(bad_uri, api)
    with pytest.raises(MCPError, match=inbox_live.DENIED):
        await service.gate(ctx, unexpected)
    current[0] = provider.tokens["alice"]
    api.company_id = "company-b"
    with pytest.raises(MCPError, match=inbox_live.DENIED):
        await service.read(uri, api)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["expired", "revoked", "selection", "mapping"])
async def test_invalid_grant_never_notifies_and_is_pruned(setup, failure):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]
    watch = service.watches[uri]
    watch.listeners = 1
    if failure == "expired":
        provider.tokens["alice"].expires_at = int(time.time()) - 1
    elif failure == "revoked":
        provider.tokens.pop("alice")
    elif failure == "mapping":
        provider.mapping.pop("alice")
    else:
        provider.companies["alice"] = "company-b"
    received = []
    service.bus.subscribe(received.append)
    await service.tick()
    assert not received and not service.watches


@pytest.mark.asyncio
async def test_poll_only_active_leases_and_publish_only_semantic_invalidation(setup, monkeypatch):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]
    watch = service.watches[uri]
    reads, received = [], []
    service.bus.subscribe(received.append)

    async def source(self, method, url, **kwargs):
        reads.append(self)
        assert self.company_id == "company-a"
        assert self._resolve_norman_token() == "norman-alice"
        return await api.arequest(method, url, **kwargs)

    monkeypatch.setattr(PinnedAPI, "arequest", source)
    current[0] = provider.tokens["bob"]  # Ambient auth must never choose polling identity.
    await service.tick()
    assert not reads  # No connected stream, no API polling.
    watch.listeners = 1
    await service.tick()
    assert len(reads) == 3 and not received  # asOf alone is not a change.
    api.count = 2
    await service.tick()
    assert len(received) == 1 and received[0].uri == uri
    assert vars(received[0]) == {"uri": uri}  # No financial data in notifications.
    assert fingerprint({"asOf": "before", "count": 1}) == fingerprint({"asOf": "after", "count": 1})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_api_authorization_failure_closes_watch_without_cached_notification(
    setup, monkeypatch, status
):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]
    watch = service.watches[uri]
    watch.listeners = 1
    api.status = status

    async def source(self, *args, **kwargs):
        return await api.arequest(*args, **kwargs)

    monkeypatch.setattr(PinnedAPI, "arequest", source)
    received = []
    service.bus.subscribe(received.append)
    await service.tick()
    assert not service.watches and not received


@pytest.mark.asyncio
async def test_revoke_during_awaited_observation_and_read_fails_closed(setup, monkeypatch):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]
    watch = service.watches[uri]
    watch.listeners = 1
    received = []
    service.bus.subscribe(received.append)

    async def revoke(_api, _page, **_kwargs):
        provider.mapping.pop("alice", None)
        await asyncio.sleep(0)
        return {"companyId": "company-a", "summary": {"approvals": 999}}, False

    monkeypatch.setattr(service, "snapshot", revoke)
    await service.observe(watch)
    assert not received
    provider.mapping["alice"] = "norman-alice"
    with pytest.raises(MCPError, match=inbox_live.DENIED):
        await service.read(uri, api)


@pytest.mark.asyncio
async def test_switch_invalidates_before_await_even_when_switch_returns_to_original_company(setup):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]
    ctx = SimpleNamespace(method="tools/call", params={"name": "switch_company"})

    async def switch(_):
        assert uri not in service.watches
        await asyncio.sleep(0)
        provider.companies["alice"] = "company-b"
        provider.companies["alice"] = "company-a"

    await service.gate(ctx, switch)
    with pytest.raises(MCPError, match=inbox_live.DENIED):
        await service.read(uri, api)


def test_pinned_client_never_falls_back_to_ambient_or_env_credentials(setup, monkeypatch):
    service, provider, current, api = setup
    watch = inbox_live.Watch(
        "uri", "alice", "client", "company-a", "company-a", 1, time.time() + 300, "hash"
    )
    pinned = PinnedAPI(provider, watch)
    current[0] = provider.tokens["bob"]
    assert pinned.company_id == "company-a"
    assert pinned._resolve_norman_token() == "norman-alice"
    provider.mapping.pop("alice")
    assert pinned._resolve_norman_token() is None
    assert pinned._refresh_oauth_norman_token() is None
    monkeypatch.setattr(pinned, "authenticate", lambda: pytest.fail("env login must never run"))
    assert "error" in pinned._make_request(
        "GET", "https://api.norman.finance/api/v1/assistant/approvals/"
    )
    service.close()
    assert not service.watches


@pytest.mark.asyncio
async def test_shutdown_during_open_does_not_recreate_watch(setup, monkeypatch):
    service, provider, current, api = setup

    async def shutdown(_api, _page, **_kwargs):
        service.close()
        await asyncio.sleep(0)
        return {"summary": {}, "unavailable": []}, False

    monkeypatch.setattr(service, "snapshot", shutdown)
    with pytest.raises(ToolError, match=inbox_live.DENIED):
        await service.open(api, 1)
    assert service.closed and not service.watches


@pytest.mark.asyncio
async def test_one_failed_observer_does_not_kill_other_watches_or_next_cycle(setup, monkeypatch):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]
    service.watches[uri].listeners = 1
    current[0] = provider.tokens["bob"]
    other = (await service.open(api, 1))["resourceUri"]
    service.watches[other].listeners = 1
    calls = []

    async def observe(watch):
        calls.append(watch.uri)
        if watch.uri == uri:
            raise RuntimeError("untrusted source detail must not be logged")

    monkeypatch.setattr(service, "observe", observe)
    await service.tick()
    await service.tick()
    assert calls == [uri, other, uri, other]


@pytest.mark.asyncio
async def test_all_snapshot_paths_share_bounded_concurrency(setup, monkeypatch):
    service, provider, current, api = setup
    active, peak = 0, 0

    async def slow_load(_api, _page):
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        await asyncio.sleep(0.01)
        active -= 1
        return {"summary": {}}

    monkeypatch.setattr(inbox_live, "load_inbox", slow_load)
    await asyncio.gather(*(service.snapshot(api, page) for page in range(20)))
    assert peak == 4 and active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 302])
async def test_native_observer_http_pins_auth_company_and_never_redirects_or_reauthenticates(
    monkeypatch, status
):
    import httpx

    provider = Provider()
    watch = inbox_live.Watch(
        "uri", "alice", "client", "company-a", "company-a", 1, time.time() + 300, "hash"
    )
    pinned = PinnedAPI(provider, watch)
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer norman-alice"
        assert request.headers["X-Company-Id"] == "company-a"
        assert request.url.params["page"] == "2"
        return httpx.Response(
            status, json={"runs": []}, headers={"Location": "https://other.invalid/"}
        )

    original = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs == {"timeout": 10.0, "follow_redirects": False, "trust_env": False}
        return original(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(inbox_live.httpx, "AsyncClient", client)
    monkeypatch.setattr(pinned, "authenticate", lambda: pytest.fail("no ambient reauthentication"))
    result = await pinned.arequest(
        "GET", "https://api.norman.finance/api/v1/assistant/workflow-runs/", params={"page": 2}
    )
    assert len(requests) == 1
    if status == 200:
        assert result == {"runs": []}
    else:
        assert result["status_code"] == status and "error" in result


@pytest.mark.asyncio
async def test_canceled_native_http_read_stops_its_transport(monkeypatch):
    import httpx

    provider = Provider()
    watch = inbox_live.Watch(
        "uri", "alice", "client", "company-a", "company-a", 1, time.time() + 300, "hash"
    )
    pinned = PinnedAPI(provider, watch)
    started, stopped = asyncio.Event(), asyncio.Event()

    async def slow(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    original = httpx.AsyncClient
    monkeypatch.setattr(
        inbox_live.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(slow)),
    )
    task = asyncio.create_task(
        pinned.arequest("GET", "https://api.norman.finance/api/v1/assistant/workflow-runs/")
    )
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


# --- Regression tests for the review of #149 ---------------------------------


@pytest.mark.asyncio
async def test_expired_norman_token_is_refreshed_through_the_watch_grant(monkeypatch):
    import httpx

    provider = Provider()
    refreshed = []

    def refresh(token):
        refreshed.append(token)
        provider.mapping[token] = "norman-alice-2"
        return "norman-alice-2"

    provider.refresh_norman_token_sync = refresh
    watch = inbox_live.Watch(
        "uri", "alice", "client", "company-a", "company-a", 1, time.time() + 300, "hash"
    )

    def handle(request):
        if request.headers["Authorization"] == "Bearer norman-alice":
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json={"runs": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    result = await PinnedAPI(provider, watch, client).arequest(
        "GET", "https://api.norman.finance/api/v1/assistant/workflow-runs/"
    )
    assert result == {"runs": []}
    assert refreshed == ["alice"]  # the watch's own grant


@pytest.mark.asyncio
async def test_lease_company_is_resolved_off_the_event_loop(setup):
    import threading

    service, provider, current, api = setup
    threads = []

    class ThreadAwareAPI(API):
        @property
        def company_id(self):
            threads.append(threading.current_thread())
            return "company-a"

    await service.open(ThreadAwareAPI(), 1)
    assert threads and threading.main_thread() not in threads


@pytest.mark.asyncio
async def test_one_token_cannot_hold_every_snapshot_read(setup, monkeypatch):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]
    release = asyncio.Event()
    original = inbox_live.load_inbox

    async def slow(observed, page):
        await release.wait()
        return await original(observed, page)

    monkeypatch.setattr(inbox_live, "load_inbox", slow)
    held = [asyncio.create_task(service.read(uri, api)) for _ in range(inbox_live.MAX_READS_PER_TOKEN)]
    await asyncio.sleep(0.05)
    with pytest.raises(MCPError, match="busy"):
        await service.read(uri, api)
    release.set()
    await asyncio.gather(*held)
    assert not service._reads


@pytest.mark.asyncio
async def test_listen_gate_surfaces_sdk_errors_instead_of_an_exception_group(setup):
    service, provider, current, api = setup
    uri = (await service.open(api, 1))["resourceUri"]

    async def refused(_ctx):
        raise MCPError(-32603, "Subscription limit reached")

    ctx = SimpleNamespace(
        method="subscriptions/listen",
        params={"notifications": {"resourceSubscriptions": [uri]}},
        lifespan_context={"api": api},
        request_id=7,
    )
    with pytest.raises(MCPError, match="Subscription limit reached") as exc:
        await service.gate(ctx, refused)
    assert exc.value.code == -32603
    assert service.listeners == 0


@pytest.mark.parametrize("transport, enabled", [("streamable-http", True), ("sse", False)])
def test_live_inbox_only_runs_on_streamable_http(monkeypatch, tmp_path, transport, enabled):
    import norman_mcp.auth.provider as provider_module
    import norman_mcp.context as context_module
    from norman_mcp.server import create_app

    monkeypatch.setattr(provider_module, "_STATE_FILE", str(tmp_path / "oauth.json"))
    monkeypatch.setattr(context_module, "oauth_provider", context_module.oauth_provider)
    monkeypatch.setattr(context_module, "_api_client", context_module._api_client)
    monkeypatch.setenv("NORMAN_MCP_INBOX_LIVE", "1")
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)

    server = create_app(transport=transport)

    # SSE enters the lifespan once per connection; a process-wide observer there
    # would multiply per client and close for everyone on the first disconnect.
    assert (getattr(server, "_inbox_live", None) is not None) is enabled


@pytest.mark.asyncio
async def test_refreshed_tokens_of_one_grant_share_the_lease_limit(setup, monkeypatch):
    service, provider, current, api = setup
    provider.tokens["alice-refreshed"] = provider.tokens["alice"].model_copy(
        update={"token": "alice-refreshed"}
    )
    provider.mapping["alice-refreshed"] = "norman-alice-2"
    provider.companies["alice-refreshed"] = "company-a"
    provider.grant_for_token = lambda token: {"alice": "g1", "alice-refreshed": "g1"}.get(token, token)
    monkeypatch.setattr(inbox_live, "MAX_PER_GRANT", 1)

    await service.open(api, 1)
    current[0] = provider.tokens["alice-refreshed"]
    with pytest.raises(ToolError, match="limit"):
        await service.open(api, 2)  # a refresh does not buy another lease
    current[0] = provider.tokens["bob"]
    assert (await service.open(api, 2))["page"] == 2  # a different grant still can
