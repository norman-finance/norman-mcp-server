"""Exercise SDK 2 startup and concurrent OAuth identity through real MCP HTTP."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

from mcp.client import Client
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from norman_mcp import context
from norman_mcp.api.client import NormanAPI
from norman_mcp.context import Context
from norman_mcp.server import create_app, create_cors_app


def test_shared_startup_client_resolves_oauth_identity_per_http_request(monkeypatch, tmp_path):
    monkeypatch.setattr("norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "oauth.json"))
    previous_provider = context.get_oauth_provider()
    previous_client = context.get_api_client()
    server = create_app(transport="streamable-http", streamable_http_options={"stateless": True})
    provider = context.get_oauth_provider()
    for caller in ("alice", "bob"):
        token = "mcp-" + caller
        provider.tokens[token] = AccessToken(
            token=token, client_id="fixture", scopes=["read"], expires_at=int(time.time()) + 3600
        )
        provider.token_mapping[token] = "norman-" + caller
        provider.token_to_company_id[token] = "company-" + caller

    @server.tool()
    async def identity_probe(ctx: Context) -> dict[str, str]:
        api = ctx.request_context.lifespan_context["api"]
        assert api.token_source == "oauth"  # Lifespan runs outside a bearer context.
        company = api.company_id
        token = api._resolve_norman_token()
        await asyncio.sleep(0.02)  # Interleave requests on the same server-wide API client.
        assert api.company_id == company
        assert api._resolve_norman_token() == token
        return {"companyId": company, "token": token}

    try:
        with TestClient(create_cors_app(server), base_url="http://localhost:3001") as client:

            def call(caller, modern):
                params = {"name": "identity_probe", "arguments": {}}
                headers = {
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer mcp-" + caller,
                    "MCP-Protocol-Version": "2025-11-25",
                }
                if modern:
                    headers.update(
                        {
                            "MCP-Protocol-Version": "2026-07-28",
                            "MCP-Method": "tools/call",
                            "MCP-Name": "identity_probe",
                        }
                    )
                    params["_meta"] = {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                response = client.post(
                    "/mcp",
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
                )
                assert response.status_code == 200, response.text
                result = response.json()["result"]
                assert not result.get("isError"), response.text
                data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
                assert data == {"companyId": "company-" + caller, "token": "norman-" + caller}

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(
                    pool.map(
                        lambda args: call(*args),
                        [("alice", False), ("bob", False), ("alice", True), ("bob", True)],
                    )
                )
    finally:
        context.set_oauth_provider(previous_provider)
        context.set_api_client(previous_client)


def test_stdio_static_resources_use_the_authenticated_lifespan_client(monkeypatch):
    monkeypatch.setenv("NORMAN_EMAIL", "fixture@example.test")
    monkeypatch.setenv("NORMAN_PASSWORD", "fixture-only")
    previous_client = context.get_api_client()

    async def authenticate(api):
        api.access_token = "norman-fixture"
        api.token_source = "env"
        api._env_company_id = "company-fixture"
        return True

    def source(api, method, url, **kwargs):
        assert api.access_token == "norman-fixture"
        assert url.endswith("/companies/company-fixture/")
        return {"name": "Fixture Company"}

    monkeypatch.setattr("norman_mcp.server.authenticate_with_credentials", authenticate)
    monkeypatch.setattr(NormanAPI, "_make_request", source)
    server = create_app(transport="stdio")

    async def read():
        async with Client(server, mode="legacy", raise_exceptions=True) as client:
            result = await client.read_resource("company://current")
            assert "Fixture Company" in result.contents[0].text

    try:
        asyncio.run(read())
    finally:
        context.set_api_client(previous_client)
