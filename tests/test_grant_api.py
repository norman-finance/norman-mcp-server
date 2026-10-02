"""Native Inbox list parity and read-only grant/company boundaries."""

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.subscriptions import InMemorySubscriptionBus

from norman_mcp import config
from norman_mcp.api.grant import GrantAPI
from norman_mcp.apps import inbox_live
from norman_mcp.apps.inbox import read_list
from norman_mcp.apps.inbox_live import InboxLive, ObservedAPI, PinnedAPI, Watch

ORIGIN = "https://api.norman.finance/"
COMPANY = "11111111-1111-4111-8111-111111111111"


class Provider:
    def __init__(self):
        self.norman_token = "norman-alice"
        self.refreshed = []
        self.tokens = {
            "alice": AccessToken(
                token="alice", client_id="client-a", scopes=[], expires_at=int(time.time()) + 3600
            )
        }

    def get_norman_token(self, token):
        assert token == "alice"
        return self.norman_token

    def get_company_for_token(self, token):
        assert token == "alice"
        return COMPANY

    def refresh_norman_token_sync(self, token):
        assert token == "alice"
        self.refreshed.append(token)
        self.norman_token = "norman-alice-refreshed"
        return self.norman_token


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(config, "api_base_url", ORIGIN)
    return Provider()


def watch():
    return Watch("uri", "alice", "client-a", COMPANY, COMPANY, 1, time.time() + 300, "hash")


@pytest.mark.asyncio
@pytest.mark.parametrize("runs", [[], [{"publicId": "run-1", "status": "ready_for_approval"}]])
async def test_native_autofiling_list_reaches_the_real_inbox_reader(provider, runs):
    def handle(request):
        assert request.method == "GET"
        assert request.url.path == f"/api/v1/companies/{COMPANY}/autofiling/runs/"
        assert request.headers["Authorization"] == "Bearer norman-alice"
        assert request.headers["X-Company-Id"] == COMPANY
        return httpx.Response(200, json=runs)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await read_list(
            PinnedAPI(provider, watch(), client), f"companies/{COMPANY}/autofiling/runs/"
        )
    assert result == runs


@pytest.mark.asyncio
async def test_list_retry_keeps_the_watch_grant_and_company(provider):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["X-Company-Id"] == COMPANY
        if len(requests) == 1:
            assert request.headers["Authorization"] == "Bearer norman-alice"
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer norman-alice-refreshed"
        return httpx.Response(200, json=[{"publicId": "run-1"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        data = await PinnedAPI(provider, watch(), client).arequest(
            "GET", ORIGIN + f"api/v1/companies/{COMPANY}/autofiling/runs/"
        )
    assert data == [{"publicId": "run-1"}]
    assert len(requests) == 2 and provider.refreshed == ["alice"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 302])
async def test_native_reads_preserve_auth_failures_and_do_not_follow_redirects(provider, status):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://other.invalid/"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=True
    ) as client:
        observed = ObservedAPI(PinnedAPI(provider, watch(), client))
        result = await observed.arequest("GET", ORIGIN + "api/v1/accounting/transactions/")
    assert result["status_code"] == status and result["error"]
    assert observed.denied == (status in (401, 403))
    assert len(requests) == (2 if status == 401 else 1)
    assert all(request.url.host == "api.norman.finance" for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_every_native_write_method_is_forbidden_before_http(provider, method):
    def unexpected(request):
        pytest.fail("A rejected native request must not reach HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        for api in (
            GrantAPI(provider, "alice", COMPANY, client=client),
            PinnedAPI(provider, watch(), client),
        ):
            with pytest.raises(ValueError, match="trusted API reads"):
                await api.arequest(
                    method,
                    ORIGIN + "api/v1/accounting/transactions/complex-filter/",
                    params={"page": 1, "page_size": 1},
                    json_data={"status": "UNVERIFIED"},
                )
    assert provider.refreshed == []


@pytest.mark.asyncio
async def test_missing_grant_token_does_not_use_ambient_credentials(provider, monkeypatch):
    provider.norman_token = None
    monkeypatch.setenv("NORMAN_EMAIL", "ambient@example.invalid")
    monkeypatch.setenv("NORMAN_PASSWORD", "ambient-password")

    def unexpected(request):
        pytest.fail("Missing grant credentials must not reach HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        result = await PinnedAPI(provider, watch(), client).arequest(
            "GET", ORIGIN + "api/v1/accounting/transactions/"
        )
    assert result["status_code"] == 401 and provider.refreshed == []


@pytest.mark.asyncio
async def test_canceling_native_list_read_stops_the_async_transport(provider):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def slow(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        task = asyncio.create_task(
            GrantAPI(provider, "alice", COMPANY, client=client).arequest(
                "GET", ORIGIN + f"api/v1/companies/{COMPANY}/autofiling/runs/"
            )
        )
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stopped.is_set() and provider.refreshed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [False, True])
async def test_native_watch_uses_all_source_availability_not_legacy_three_count(
    provider, monkeypatch, available
):
    monkeypatch.setattr(inbox_live, "get_access_token", lambda: provider.tokens["alice"])
    service = InboxLive(provider, InMemorySubscriptionBus())

    async def snapshot(*args, **kwargs):
        return {
            "summary": {},
            "unavailable": ["workflows", "approvals", "tax reviews"],
            "sourceAvailability": {
                "workflows": False,
                "approvals": False,
                "tax reviews": False,
                "bank balances": available,
                "transactions": False,
                "overdue invoices": False,
                "unattached documents": False,
                "transactions awaiting review": False,
            },
        }, False

    monkeypatch.setattr(service, "snapshot", snapshot)
    if available:
        result = await service.open(SimpleNamespace(company_id=COMPANY), 1)
        assert result["resourceUri"] in service.watches
    else:
        with pytest.raises(ToolError, match=inbox_live.DENIED):
            await service.open(SimpleNamespace(company_id=COMPANY), 1)
        assert not service.watches
