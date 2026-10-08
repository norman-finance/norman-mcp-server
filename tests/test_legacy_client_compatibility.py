"""Legacy clients keep their handshake, tools, resources and prompt wire contracts.

The inventory oracle was captured from origin/main (6b2cec4) with SDK 1.26.
These tests deliberately use raw JSON-RPC instead of the new SDK's client, so
SDK 2 client/server changes cannot hide a wire incompatibility from the test.
New tools may be added freely. Intentional changes to an existing wire contract
must update its oracle signature after compatibility review; never regenerate
every signature simply to accept an SDK upgrade.

The OpenAI plugin update intentionally revises safety annotations, the legacy
category-template display title, the bounded SKR suggestion description and the
corporate people tool's government-identifier boundary. Only those 16 legacy
tool signatures were updated; request methods, tool names and unrelated
schemas remain covered by the original oracle.

The October 3 review remediation updates six more metadata signatures:
link_transaction and update_asset disclose destructive side effects;
apply_rule_to_existing is destructive and non-idempotent; upload_bulk_attachments,
create_attachment and suggest_skr_category use neutral descriptions.
Only description text within input schemas changes; accepted arguments do not.
Company responses intentionally omit PESEL while retaining business identifiers.

The October 5 correction-sign change updates three descriptions: cancel_invoice,
create_credit_note and create_invoice say that a correction's amounts stay
positive and print with a minus. create_invoice and update_invoice also gain the
optional preceding_invoice_number and preceding_invoice_date of a correction
made from scratch; no existing argument changes.

The October 5 Finanzamt finder updates two descriptions: update_corporate_company
points to suggest_tax_office for the tax office, and update_corporate_vat_and_bank
states the founding-year Kleinunternehmer limit. No argument changes.

The October 6 duplicate change updates one description: duplicate_invoice says
the copy keeps the bank details of the original; no argument changes.
"""

import asyncio
import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from norman_mcp.context import (
    get_api_client,
    get_oauth_provider,
    set_api_client,
    set_oauth_provider,
)
from norman_mcp.server import create_app, create_cors_app

VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
FIXTURES = Path(__file__).parent / "fixtures"
ORACLE = json.loads((FIXTURES / "sdk1_legacy_inventory.json").read_text())
COMPANY = {"publicId": "company-compat-fixture", "name": "Compatibility Fixture", "isSme": False}


@pytest.fixture(autouse=True)
def restore_process_context():
    """Offline lifespans and create_app must not replace another test's globals."""
    api, provider = get_api_client(), get_oauth_provider()
    try:
        yield
    finally:
        set_api_client(api)
        set_oauth_provider(provider)


class OfflineAPI:
    company_id = COMPANY["publicId"]

    def _make_request(self, method, url, **kwargs):
        assert method == "GET", "Compatibility tests must never mutate data"
        return COMPANY.copy()

    async def arequest(self, method, url, **kwargs):
        return self._make_request(method, url, **kwargs)


class OfflineVerifier:
    async def verify_token(self, token):
        if token == "compat-fixture-token":
            return AccessToken(token=token, client_id="compat-fixture-client", scopes=[])
        return None


@asynccontextmanager
async def offline_lifespan(_):
    api = OfflineAPI()
    set_api_client(api)
    yield {"api": api}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def assert_inventory(result, catalog, key):
    actual = {item[key]: digest(item) for item in result[catalog]}
    expected = ORACLE[catalog]
    assert expected.keys() <= actual.keys(), f"Legacy {catalog} were removed"
    assert {
        name: actual[name] for name in expected
    } == expected, f"Legacy {catalog} wire metadata changed"


def requests_for(version):
    return (
        (
            "initialize",
            {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "legacy-wire-fixture", "version": "1"},
            },
        ),
        ("tools/list", {}),
        ("resources/list", {}),
        ("resources/templates/list", {}),
        ("prompts/list", {}),
        ("tools/call", {"name": "get_company_details", "arguments": {}}),
        ("resources/read", {"uri": "company://current"}),
        ("resources/read", {"uri": "transactions://list/1/100"}),
        (
            "prompts/get",
            {"name": "create_client_prompt", "arguments": {"name": "Compatibility Fixture"}},
        ),
    )


def assert_results(version, results):
    assert results[0]["protocolVersion"] == version
    assert "events" not in results[0]["capabilities"]
    assert_inventory(results[1], "tools", "name")
    assert_inventory(results[2], "resources", "uri")
    assert_inventory(results[3], "resourceTemplates", "uriTemplate")
    assert_inventory(results[4], "prompts", "name")
    tool = results[5]
    assert not tool.get("isError", False)
    assert json.loads(tool["content"][0]["text"]) == COMPANY
    assert tool["structuredContent"] == {"result": COMPANY}
    assert "Compatibility Fixture" in results[6]["contents"][0]["text"]
    assert "company-compat-fixture" in results[7]["contents"][0]["text"]
    assert "Compatibility Fixture" in results[8]["messages"][0]["content"]["text"]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("stateless", (True, False), ids=("stateless", "stateful"))
def test_legacy_http_wire_contract(version, stateless, monkeypatch, tmp_path):
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)
    monkeypatch.setattr(
        "norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "offline-oauth-state.json")
    )
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_ID", "")
    server = create_app(
        host="127.0.0.1",
        public_url="http://localhost:8000",
        transport="streamable-http",
        streamable_http_options={"stateless": stateless, "json_response": True},
    )
    server._lowlevel_server.lifespan = offline_lifespan
    server._token_verifier = OfflineVerifier()
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
        "Authorization": "Bearer compat-fixture-token",
    }
    results = []
    with TestClient(create_cors_app(server), base_url="http://localhost:8000") as client:
        assert client.post("/mcp", json={}).status_code == 401
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
                if not stateless:
                    headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
                notification = client.post(
                    "/mcp",
                    headers=headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )
                assert notification.status_code == 202
    assert_results(version, results)


@pytest.mark.parametrize("version", VERSIONS)
def test_legacy_stdio_wire_contract(version, tmp_path):
    async def exercise():
        env = os.environ.copy()
        env["MCP_OAUTH_STATE_FILE"] = str(tmp_path / "offline-oauth-state.json")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(FIXTURES / "legacy_stdio_server.py"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            limit=2**20,
        )
        results = []
        try:
            for request_id, (method, params) in enumerate(requests_for(version), 1):
                request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
                process.stdin.write(json.dumps(request).encode() + b"\n")
                await process.stdin.drain()
                wire = json.loads(await asyncio.wait_for(process.stdout.readline(), timeout=15))
                assert wire["id"] == request_id and "error" not in wire, wire
                results.append(wire["result"])
                if method == "initialize":
                    process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                    await process.stdin.drain()
            return results
        finally:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    assert_results(version, asyncio.run(exercise()))
