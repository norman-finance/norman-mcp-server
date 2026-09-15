import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent
from starlette.testclient import TestClient

from norman_mcp.apps.public import APP_RESOURCE_URI, TAX_APP_RESOURCE_URI
from norman_mcp.chatgpt import (
    CHATGPT_MCP_PATH,
    CHATGPT_WIDGET_DOMAIN,
    PAYMENT_CAPABLE_TOOLS,
    REGISTRATION_MODULES,
    ChatGPTMCP,
    _safe_result,
    create_chatgpt_server,
)
from norman_mcp.server import create_cors_app, mcp


def test_profile_is_isolated_and_does_not_replace_oauth_or_default_tools():
    before = set(mcp._tool_manager._tools)
    server = create_chatgpt_server(mcp)
    tools = server._tool_manager._tools
    assert set(mcp._tool_manager._tools) == before
    assert PAYMENT_CAPABLE_TOOLS <= before
    assert not PAYMENT_CAPABLE_TOOLS & tools.keys()
    assert not any(t.fn.__module__ in REGISTRATION_MODULES for t in tools.values())
    assert server._auth_server_provider is mcp._auth_server_provider
    assert server.settings.auth == mcp.settings.auth
    assert server.settings.streamable_http_path == CHATGPT_MCP_PATH
    assert "get_norman_workspace" in tools
    assert "create_invoice" in tools
    assert "set_corporate_people" not in tools


def test_chatgpt_resources_use_owned_origin_and_no_legacy_identity_resources():
    server = create_chatgpt_server(mcp)
    resources = asyncio.run(server.list_resources())
    assert {str(r.uri) for r in resources} == {APP_RESOURCE_URI, TAX_APP_RESOURCE_URI}
    for resource in resources:
        assert resource.meta["ui"]["domain"] == CHATGPT_WIDGET_DOMAIN
        assert resource.meta["openai/widgetDomain"] == CHATGPT_WIDGET_DOMAIN
        assert resource.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}


@pytest.mark.parametrize(
    "name", ["get_incorporation", "get_gewerbe_registration", "get_corporate_tax_registration"]
)
@pytest.mark.parametrize(
    "api_result,exists",
    [
        ({"status_code": 404, "error": "Resource not found"}, False),
        (
            {
                "status": "data_collection",
                "taxId": "restricted-fixture",
                "dob": "private-fixture",
                "representatives": [{"taxId": "private"}],
                "reportUrl": "private-url",
            },
            True,
        ),
    ],
)
def test_registration_status_never_returns_full_identity_records(name, api_result, exists):
    calls = []

    async def request(method, url):
        calls.append((method, url))
        return api_result

    ctx = SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context={"api": SimpleNamespace(arequest=request)})
    )
    server = create_chatgpt_server(mcp)
    result = asyncio.run(server._tool_manager._tools[name].fn(ctx))
    assert result["exists"] is exists
    assert set(result) == {"exists", "status", "workspaceUrl", "nextStep"}
    assert result["workspaceUrl"].startswith("https://app.norman.finance/")
    assert "private" not in json.dumps(result)
    assert len(calls) == 1 and calls[0][0] == "GET"


def test_registration_auth_failure_is_not_reported_as_no_registration():
    async def request(*_):
        return {"status_code": 401, "error": "Expired token"}

    ctx = SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context={"api": SimpleNamespace(arequest=request)})
    )
    server = create_chatgpt_server(mcp)
    result = asyncio.run(server._tool_manager._tools["get_incorporation"].fn(ctx))
    assert "error" in result
    assert "exists" not in result


def test_workspace_navigation_does_not_call_any_backend():
    server = create_chatgpt_server(mcp)
    result = asyncio.run(server._tool_manager._tools["get_norman_workspace"].fn("bills"))
    assert result == {"workspaceUrl": "https://app.norman.finance/bills", "actionPerformed": False}


def test_known_identity_fields_removed_from_both_tool_result_channels():
    original = {
        "amount": 12,
        "people": [{"taxId": "restricted-fixture", "dob": "private-fixture"}],
        "taxNumber": "business-number",
    }
    result = CallToolResult(
        content=[TextContent(type="text", text=json.dumps(original))],
        structuredContent=original,
        _meta={"taxId": "restricted-fixture"},
    )
    cleaned = _safe_result(result)
    assert "restricted-fixture" not in cleaned.model_dump_json()
    assert "private-fixture" not in cleaned.model_dump_json()
    assert cleaned.structuredContent["taxNumber"] == "business-number"
    assert json.loads(cleaned.content[0].text) == cleaned.structuredContent
    assert original["people"][0]["taxId"] == "restricted-fixture"


def test_protocol_rejects_identity_input_and_unregistered_payment_actions():
    async def run():
        server = create_chatgpt_server(mcp)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            listed = {t.name for t in (await client.list_tools()).tools}
            assert not listed & PAYMENT_CAPABLE_TOOLS
            for name in PAYMENT_CAPABLE_TOOLS | {"set_corporate_people"}:
                result = await client.call_tool(name, {})
                assert result.isError is True
            result = await client.call_tool(
                "create_transaction", {"items": [{"personal_tax_id": "do-not-forward"}]}
            )
            assert result.isError is True
            assert "do-not-forward" not in str(result)
            link = await client.call_tool("get_norman_workspace", {"workflow": "bills"})
            assert not link.isError
            assert link.structuredContent["actionPerformed"] is False

    asyncio.run(run())


def test_protocol_redacts_plain_dictionary_results_in_both_channels():
    async def run():
        server = ChatGPTMCP()

        @server.tool()
        async def example() -> dict[str, Any]:
            return {
                "people": [{"personal_tax_id": "restricted-fixture"}],
                "taxNumber": "business-number",
            }

        async with create_connected_server_and_client_session(server._mcp_server) as client:
            result = await client.call_tool("example", {})
            assert not result.isError
            assert "restricted-fixture" not in result.model_dump_json()
            assert result.structuredContent == {
                "people": [{}],
                "taxNumber": "business-number",
            }
            assert json.loads(result.content[0].text) == result.structuredContent

    asyncio.run(run())


def test_http_routes_require_the_same_existing_authentication():
    with TestClient(create_cors_app(mcp), base_url="http://localhost:3001") as client:
        general = client.post("/mcp", json={})
        chatgpt = client.post(CHATGPT_MCP_PATH, json={})
        assert general.status_code == chatgpt.status_code == 401
        assert general.headers["www-authenticate"] == chatgpt.headers["www-authenticate"]
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        assert metadata["authorization_endpoint"] == "http://localhost:3001/authorize"
        assert metadata["token_endpoint"] == "http://localhost:3001/token"


def test_http_transport_serves_both_profiles_with_running_lifespans():
    @asynccontextmanager
    async def lifespan(_):
        yield {"api": SimpleNamespace()}

    primary = FastMCP(lifespan=lifespan, stateless_http=True, json_response=True)

    @primary.tool()
    async def pay_bill() -> dict[str, bool]:
        return {"called": True}

    with TestClient(create_cors_app(primary), base_url="http://localhost:8000") as client:
        headers = {"Accept": "application/json, text/event-stream"}
        for path in ("/mcp", CHATGPT_MCP_PATH):
            result = client.post(
                path,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            assert result.status_code == 200
            tools = {t["name"] for t in result.json()["result"]["tools"]}
            assert ("pay_bill" in tools) is (path == "/mcp")
        result = client.post(
            CHATGPT_MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_norman_workspace", "arguments": {"workflow": "bills"}},
            },
        )
        assert result.status_code == 200
        assert result.json()["result"]["structuredContent"]["actionPerformed"] is False
