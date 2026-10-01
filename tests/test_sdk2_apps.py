"""Modern Apps negotiation augments the existing portable UI contract."""

from contextlib import asynccontextmanager

import pytest
from mcp.shared.inbound import encode_header_value
from starlette.testclient import TestClient

from norman_mcp import server as server_module
from norman_mcp.apps.public import APP_MIME_TYPE, APP_RESOURCE_URI, TAX_APP_RESOURCE_URI


@pytest.fixture
def app_server(monkeypatch):
    @asynccontextmanager
    async def offline_lifespan(_):
        # These tests only list/read UI resources and render supplied data.
        # Any unexpected API use fails instead of contacting Norman.
        yield {"api": object()}

    monkeypatch.setattr(server_module, "lifespan", offline_lifespan)
    monkeypatch.setenv("NORMAN_EMAIL", "apps-fixture@example.invalid")
    monkeypatch.setenv("NORMAN_PASSWORD", "apps-fixture-password")
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)
    # Reuse the production constructor without OAuth or credential exchange.
    return server_module.create_app(transport="stdio")


def _call(client, method, params=None, *, version="2026-07-28"):
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
    }
    if version == "2026-07-28":
        headers["MCP-Method"] = method
        name = (params or {}).get("name") or (params or {}).get("uri")
        if name:
            headers["MCP-Name"] = encode_header_value(name)
        params = {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientCapabilities": {
                    "extensions": {
                        "io.modelcontextprotocol/ui": {"mimeTypes": [APP_MIME_TYPE]},
                    },
                },
            },
        }
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        request["params"] = params
    response = client.post("/mcp", headers=headers, json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    return body["result"]


def _assert_portable_ui_contract(client, version):
    tools = {tool["name"]: tool for tool in _call(client, "tools/list", version=version)["tools"]}
    expected_resources = {
        "render_document_review": APP_RESOURCE_URI,
        "render_reconciliation_cockpit": APP_RESOURCE_URI,
        "render_ledger_explorer": APP_RESOURCE_URI,
        "render_tax_preview": TAX_APP_RESOURCE_URI,
        "render_tax_submission": TAX_APP_RESOURCE_URI,
    }
    for name, uri in expected_resources.items():
        assert tools[name]["_meta"]["ui"]["resourceUri"] == uri
        assert tools[name]["_meta"]["openai/outputTemplate"] == uri

    resources = {
        resource["uri"]: resource
        for resource in _call(client, "resources/list", version=version)["resources"]
    }
    for uri in (APP_RESOURCE_URI, TAX_APP_RESOURCE_URI):
        assert resources[uri]["mimeType"] == APP_MIME_TYPE
        result = _call(client, "resources/read", {"uri": uri}, version=version)
        content = result["contents"][0]
        assert content["mimeType"] == APP_MIME_TYPE
        assert "ui/notifications/tool-result" in content["text"]

    result = _call(
        client,
        "tools/call",
        {
            "name": "render_document_review",
            "arguments": {"payload": {"items": [{"id": "fixture-document"}]}},
        },
        version=version,
    )
    assert not result.get("isError")
    assert result["structuredContent"]["view"] == "documents"
    assert result["structuredContent"]["items"] == [{"id": "fixture-document"}]
    assert "1 visible row" in result["content"][0]["text"]


def test_modern_http_discovery_advertises_apps_and_preserves_portable_ui(app_server):
    with TestClient(
        app_server.streamable_http_app(stateless_http=True, json_response=True),
        base_url="http://localhost:8000",
    ) as client:
        result = _call(client, "server/discover")
        assert result["capabilities"]["extensions"]["io.modelcontextprotocol/ui"] == {}
        _assert_portable_ui_contract(client, "2026-07-28")


@pytest.mark.parametrize("version", ["2025-06-18", "2025-11-25"])
def test_legacy_initialize_and_portable_ui_remain_unchanged(app_server, version):
    with TestClient(
        app_server.streamable_http_app(stateless_http=True, json_response=True),
        base_url="http://localhost:8000",
    ) as client:
        result = _call(
            client,
            "initialize",
            {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "legacy-apps-fixture", "version": "1"},
            },
            version=version,
        )
        assert result["protocolVersion"] == version
        assert "extensions" not in result["capabilities"]
        _assert_portable_ui_contract(client, version)
