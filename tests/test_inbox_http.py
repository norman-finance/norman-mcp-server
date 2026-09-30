"""Exercise the hosted SDK 2 lifespan and OAuth company isolation on real MCP HTTP."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from norman_mcp import context
from norman_mcp.api.client import NormanAPI
from norman_mcp.server import create_app, create_cors_app


def test_shared_startup_client_resolves_oauth_identity_per_http_request(monkeypatch, tmp_path):
    monkeypatch.setattr("norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "oauth.json"))
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)
    server = create_app(transport="streamable-http", streamable_http_options={"stateless": True})
    provider = context.get_oauth_provider()
    for caller in ("alice", "bob"):
        token = "mcp-" + caller
        provider.tokens[token] = AccessToken(
            token=token, client_id="fixture", scopes=["read"], expires_at=int(time.time()) + 3600
        )
        provider.token_mapping[token] = "norman-" + caller
        provider.token_to_company_id[token] = "company-" + caller

    async def source(self, method, url, **kwargs):
        assert self.token_source == "oauth"  # Startup happens outside a bearer context.
        company = self.company_id
        assert self._resolve_norman_token() == "norman-" + company.removeprefix("company-")
        if url.endswith("workflow-runs/"):
            return {
                "runs": [{"publicId": company, "state": "active", "blockedReason": "user_input"}]
            }
        if url.endswith("rule-executions/"):
            return {"results": [], "count": 0, "next": None}
        return {"items": []}

    monkeypatch.setattr(NormanAPI, "arequest", source)
    with TestClient(create_cors_app(server), base_url="http://localhost:3001") as client:

        def call(caller, modern):
            params = {"name": "get_norman_inbox_data", "arguments": {}}
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
                        "MCP-Name": "get_norman_inbox_data",
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
            if modern:
                assert "structuredContent" in result, response.text
            data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
            assert data["companyId"] == "company-" + caller
            assert data["questions"][0]["publicId"] == "company-" + caller

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda args: call(*args),
                    [("alice", False), ("bob", False), ("alice", True), ("bob", True)],
                )
            )


def test_events_are_opt_in_and_worker_starts_without_caller_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr("norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "oauth.json"))
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)
    plain = create_app(transport="streamable-http")
    assert not hasattr(plain, "_event_service")
    monkeypatch.setenv("NORMAN_MCP_EVENTS_DB", str(tmp_path / "events.sqlite"))
    monkeypatch.setenv("NORMAN_MCP_EVENTS_KEY", Fernet.generate_key().decode())
    enabled = create_app(transport="streamable-http", streamable_http_options={"stateless": True})
    ticks = []

    async def tick():
        ticks.append(True)

    monkeypatch.setattr(enabled._event_service, "tick", tick)
    with TestClient(create_cors_app(enabled), base_url="http://localhost:3001"):
        assert ticks
    assert (tmp_path / "events.sqlite").stat().st_mode & 0o777 == 0o600
