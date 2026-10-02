"""Task-company assertions survive the SDK, switching and worker threads."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from norman_mcp import context
from norman_mcp.api import client as client_module
from norman_mcp.api.client import NormanAPI
from norman_mcp.context import Context, bind_company, get_bound_company_id
from norman_mcp.tools.company import register_company_tools
from norman_mcp.tools.company_scope import company_scoped
from norman_mcp.tools.transactions import register_transaction_tools

COMPANY_A = "11111111-1111-4111-8111-111111111111"
COMPANY_B = "22222222-2222-4222-8222-222222222222"
RECORD = "33333333-3333-4333-8333-333333333333"


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, **options):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn

        return register


def ctx_for(api):
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))


def result_data(result):
    data = result.structured_content or json.loads(result.content[0].text)
    # SDK 2 wraps Dict[str, Any] output under its generated result field.
    return data["result"] if isinstance(data, dict) and set(data) == {"result"} else data


@pytest.fixture(autouse=True)
def isolated_request_company():
    previous = context.get_api_company_id()
    context.set_api_company_id(None)
    assert get_bound_company_id() is None
    yield
    assert get_bound_company_id() is None
    context.set_api_company_id(previous)


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("get_company_details", {}),
        ("get_financial_overview", {}),
        ("get_transaction", {"transaction_id": RECORD}),
        ("delete_transaction", {"transaction_id": RECORD, "confirmed": True}),
    ],
)
def test_expected_company_mismatch_never_reaches_a_read_or_write(tool_name, arguments):
    api = SimpleNamespace(company_id=COMPANY_B, arequest=AsyncMock(), _make_request=Mock())
    registry = Registry()
    register_company_tools(registry)
    register_transaction_tools(registry)

    result = asyncio.run(
        registry.tools[tool_name](ctx_for(api), expected_company_id=COMPANY_A, **arguments)
    )

    assert result["code"] == "company_context_changed"
    assert "company_context" not in result
    api.arequest.assert_not_awaited()
    api._make_request.assert_not_called()


def test_invalid_expected_company_is_rejected_before_lazy_company_resolution():
    class UnresolvedApi:
        @property
        def company_id(self):
            pytest.fail("Invalid task context must not trigger the lazy /companies lookup")

    @company_scoped
    async def read(ctx: Context) -> dict:
        pytest.fail("Invalid task context must not execute the tool")

    result = asyncio.run(read(ctx_for(UnresolvedApi()), expected_company_id="not-a-company-id"))
    assert result["code"] == "invalid_company_context"


def test_legacy_call_keeps_its_payload_and_positional_arguments():
    calls = []

    @company_scoped
    async def read(ctx: Context, period: str = "year") -> dict:
        calls.append((ctx, period, get_bound_company_id()))
        return {"legacy": True}

    ctx = ctx_for(SimpleNamespace(company_id=COMPANY_A))
    assert asyncio.run(read(ctx, "quarter")) == {"legacy": True}
    assert calls == [(ctx, "quarter", None)]


def test_scoped_result_contains_verified_company_provenance():
    @company_scoped
    async def read(ctx: Context) -> dict:
        assert get_bound_company_id() == COMPANY_A
        return {"total": "123.45", "company_context": {"company_id": COMPANY_B}}

    result = asyncio.run(
        read(ctx_for(SimpleNamespace(company_id=COMPANY_A)), expected_company_id=COMPANY_A)
    )
    assert result == {"total": "123.45", "company_context": {"company_id": COMPANY_A}}


@pytest.mark.parametrize("raises", [False, True])
def test_bound_context_is_restored_on_success_and_exception(raises):
    @company_scoped
    async def read(ctx: Context) -> dict:
        assert get_bound_company_id() == COMPANY_A
        with bind_company(COMPANY_B):
            assert get_bound_company_id() == COMPANY_B
        assert get_bound_company_id() == COMPANY_A
        if raises:
            raise RuntimeError("source failed")
        return {"ok": True}

    async def run():
        try:
            return await read(
                ctx_for(SimpleNamespace(company_id=COMPANY_A)), expected_company_id=COMPANY_A
            )
        finally:
            assert get_bound_company_id() is None

    if raises:
        with pytest.raises(RuntimeError, match="source failed"):
            asyncio.run(run())
    else:
        assert asyncio.run(run())["ok"]


def test_cancellation_releases_company_binding():
    async def run():
        started = asyncio.Event()
        cleaned = []

        @company_scoped
        async def slow(ctx: Context) -> dict:
            started.set()
            await asyncio.Event().wait()
            return {}

        async def invoke():
            try:
                await slow(
                    ctx_for(SimpleNamespace(company_id=COMPANY_A)), expected_company_id=COMPANY_A
                )
            finally:
                cleaned.append(get_bound_company_id())

        task = asyncio.create_task(invoke())
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned == [None]

    asyncio.run(run())


@pytest.mark.parametrize("method", ["GET", "PATCH"])
def test_scoped_call_stays_pinned_across_concurrent_switch_and_worker_thread(monkeypatch, method):
    api = NormanAPI(authenticate_on_init=False, token_source="oauth")
    persisted = SimpleNamespace(company=COMPANY_A)
    monkeypatch.setattr(api, "_persisted_company_id", lambda: persisted.company)
    monkeypatch.setattr(api, "_resolve_norman_token", lambda: "fixture-token")
    seen = []

    def transport(**kwargs):
        seen.append((kwargs["url"], kwargs["headers"]["X-Company-Id"]))
        response = Mock(content=b"json", status_code=200)
        response.json.return_value = {"company": kwargs["headers"]["X-Company-Id"]}
        return response

    monkeypatch.setattr(client_module.requests, "request", transport)

    async def run():
        entered, switched = asyncio.Event(), asyncio.Event()

        @company_scoped
        async def read(ctx: Context) -> dict:
            entered.set()
            await switched.wait()
            # Re-resolving after a request cache is cleared must still honor
            # the task binding, including the thread that sends the HTTP call.
            context.set_api_company_id(None)
            assert api.company_id == COMPANY_A
            result = await api.arequest(
                method, "https://api.norman.finance/api/v1/accounting/transactions/"
            )
            return result

        async def switch():
            await entered.wait()
            persisted.company = COMPANY_B
            context.set_api_company_id(None)
            assert api.company_id == COMPANY_B
            assert get_bound_company_id() is None
            switched.set()

        result, _ = await asyncio.gather(
            read(ctx_for(api), expected_company_id=COMPANY_A), switch()
        )
        assert result == {"company": COMPANY_A, "company_context": {"company_id": COMPANY_A}}
        context.set_api_company_id(None)
        assert api.company_id == COMPANY_B

    asyncio.run(run())
    assert seen == [("https://api.norman.finance/api/v1/accounting/transactions/", COMPANY_A)]


def test_public_sdk_keeps_schema_optional_and_checks_scope_before_dispatch():
    api = SimpleNamespace(company_id=COMPANY_A, arequest=AsyncMock(return_value={"name": "Acme"}))

    @asynccontextmanager
    async def lifespan(server):
        yield {"api": api}

    async def run():
        server = MCPServer("scoped-company-contract", lifespan=lifespan)
        register_company_tools(server)
        register_transaction_tools(server)
        async with Client(server, mode="legacy", raise_exceptions=True) as session:
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            for name in (
                "get_financial_overview",
                "get_company_details",
                "get_transaction",
                "delete_transaction",
            ):
                schema = tools[name].input_schema
                assert "expected_company_id" in schema["properties"]
                assert "expected_company_id" not in schema.get("required", [])
                assert "ctx" not in schema["properties"]
                assert "Inbox" in schema["properties"]["expected_company_id"]["description"]
            assert tools["get_company_details"].annotations.read_only_hint is True
            assert tools["delete_transaction"].annotations.destructive_hint is True

            legacy = await session.call_tool("get_company_details", {})
            assert result_data(legacy) == {"name": "Acme"}

            scoped = await session.call_tool(
                "get_company_details", {"expected_company_id": COMPANY_A}
            )
            assert not scoped.is_error
            assert result_data(scoped) == {
                "name": "Acme",
                "company_context": {"company_id": COMPANY_A},
            }

            api.arequest.reset_mock()
            mismatched = await session.call_tool(
                "delete_transaction",
                {
                    "transaction_id": RECORD,
                    "confirmed": True,
                    "expected_company_id": COMPANY_B,
                },
            )
            assert result_data(mismatched)["code"] == "company_context_changed"
            api.arequest.assert_not_awaited()

    asyncio.run(run())


def test_sdk_preview_keeps_content_and_metadata_while_attaching_company_provenance():
    api = SimpleNamespace(company_id=COMPANY_A)
    invoked = []
    original = CallToolResult(
        content=[TextContent(type="text", text="Preview ready.")],
        meta={"norman/view": "documents"},
    )

    @asynccontextmanager
    async def lifespan(server):
        yield {"api": api}

    async def run():
        server = MCPServer("scoped-preview-contract", lifespan=lifespan)

        @server.tool(meta={"ui": {"resourceUri": "ui://fixture/preview"}})
        @company_scoped
        async def preview(ctx: Context) -> CallToolResult:
            invoked.append(get_bound_company_id())
            return original

        async with Client(server, mode="legacy", raise_exceptions=True) as session:
            descriptor = next(
                tool for tool in (await session.list_tools()).tools if tool.name == "preview"
            )
            assert descriptor.meta["ui"]["resourceUri"] == "ui://fixture/preview"
            legacy = await session.call_tool("preview", {})
            assert legacy.meta == {"norman/view": "documents"}
            scoped = await session.call_tool("preview", {"expected_company_id": COMPANY_A})
            assert scoped.meta == {"norman/view": "documents", "norman/companyId": COMPANY_A}
            assert scoped.content == original.content
            assert original.meta == {"norman/view": "documents"}
            mismatch = await session.call_tool("preview", {"expected_company_id": COMPANY_B})
            assert result_data(mismatch)["code"] == "company_context_changed"
        assert invoked == [None, COMPANY_A]

    asyncio.run(run())
