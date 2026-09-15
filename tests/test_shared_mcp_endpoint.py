"""All connectors use the original authenticated MCP route and tool inventory."""

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from norman_mcp.server import create_cors_app, mcp


def test_shared_endpoint_retains_auth_and_full_tool_inventory():
    tools = mcp._tool_manager._tools
    assert {
        "pay_bill",
        "toggle_agent",
        "set_corporate_people",
        "add_incorporation_shareholder",
    } <= tools.keys()
    assert "get_norman_workspace" not in tools
    with TestClient(create_cors_app(mcp), base_url="http://localhost:3001") as client:
        response = client.post("/mcp", json={})
        assert response.status_code == 401
        assert "oauth-protected-resource" in response.headers["www-authenticate"]
        assert client.post("/chatgpt/mcp", json={}).status_code == 404
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        assert metadata["authorization_endpoint"] == "http://localhost:3001/authorize"
        assert metadata["token_endpoint"] == "http://localhost:3001/token"


def test_shared_http_transport_keeps_the_original_lifespan():
    @asynccontextmanager
    async def lifespan(_):
        yield {}

    primary = FastMCP(lifespan=lifespan, stateless_http=True, json_response=True)

    @primary.tool()
    async def example() -> dict[str, bool]:
        return {"called": True}

    with TestClient(create_cors_app(primary), base_url="http://localhost:8000") as client:
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "example", "arguments": {}},
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["structuredContent"]["called"] is True
        assert client.post("/chatgpt/mcp", json={}).status_code == 404
