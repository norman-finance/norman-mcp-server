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
    # create_app replaces the process-wide provider and API client; put them back.
    monkeypatch.setattr(context, "oauth_provider", context.oauth_provider)
    monkeypatch.setattr(context, "_api_client", context._api_client)
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
        if url.endswith(f"companies/{company}/"):
            return {
                "publicId": company,
                "name": "Business " + company,
                "accountType": "GmbH" if company == "company-alice" else "freelancer",
                "country": "DE",
                "isSme": company == "company-alice",
                "isArchived": False,
                "chartOfAccounts": {"code": "skr04"},
                "taxNumber": "private-" + company,
            }
        if url.endswith("workflow-runs/"):
            return {
                "runs": [{"publicId": company, "state": "active", "blockedReason": "user_input"}]
            }
        if url.endswith("rule-executions/"):
            return {"results": [], "count": 0, "next": None}
        if url.endswith("autofiling/runs/"):
            assert url.endswith(f"companies/{company}/autofiling/runs/")
            return []
        if url.endswith("balance/"):
            assert url.endswith(f"companies/{company}/balance/")
            return {
                "bankAccounts": [company],
                "sumsByCurrency": [{"currency": "EUR", "sumAmount": "12.34"}],
            }
        assert method == "GET"
        if url.endswith(("transactions/", "invoices/", "attachments/")):
            return {"count": 7 if company == "company-alice" else 19, "results": []}
        raise AssertionError(url)

    monkeypatch.setattr(NormanAPI, "arequest", source)
    with TestClient(create_cors_app(server), base_url="http://localhost:3001") as client:

        def call(caller, modern, name):
            params = {"name": name, "arguments": {}}
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
                        "MCP-Name": name,
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
            assert data["capabilities"] == {"ledger": caller == "alice", "taxPreview": False}
            assert data["company"] == {
                "id": "company-" + caller,
                "name": "Business company-" + caller,
                "legalForm": "GmbH" if caller == "alice" else "freelancer",
                "country": "DE",
                "isSme": caller == "alice",
                "isArchived": False,
            }
            assert "private-" not in str(data)
            assert data["questions"][0]["publicId"] == "company-" + caller
            assert data["overview"]["actions"]["unreviewedTransactions"] == (
                7 if caller == "alice" else 19
            )
            assert data["overview"]["bankBalances"]["values"] == [
                {"currency": "EUR", "amount": "12.34"}
            ]
            if name == "open_norman_inbox":
                text = result["content"][0]["text"]
                assert "1 workflows awaiting your answer" in text
                assert "0 pending automation approvals" in text
                assert "0 tax reviews." in text
                assert "unfinalized transactions (UNVERIFIED, all history)" in text
                assert "do not claim that a screen opened" in text

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda args: call(*args),
                    [
                        ("alice", False, "get_norman_inbox_data"),
                        ("bob", False, "open_norman_inbox"),
                        ("alice", True, "open_norman_inbox"),
                        ("bob", True, "get_norman_inbox_data"),
                    ],
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
