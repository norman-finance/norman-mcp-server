"""Tax preview failures stay actionable on the actual MCP wire without leaking internals."""

from contextlib import asynccontextmanager

import pytest
import requests
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from norman_mcp import context
from norman_mcp.server import create_app, create_cors_app

PRIVATE_DETAIL = "https://api.example.invalid/private?token=do-not-expose"


class PreviewAPI:
    company_id = "preview-fixture-company"

    def __init__(self, failure):
        self.failure = failure
        self.calls = []

    def _make_request(self, method, url, **kwargs):
        # This is an offline preview response, never a Norman API request.
        assert method == "POST"
        assert url.endswith("/preview-fixture-report/generate-preview-url/")
        self.calls.append((method, url))
        if self.failure is not None:
            raise self.failure
        return {}


class PreviewVerifier:
    async def verify_token(self, token):
        if token == "preview-fixture-token":
            return AccessToken(token=token, client_id="preview-fixture-client", scopes=[])
        return None


@pytest.mark.parametrize("version", ("2025-11-25", "2026-07-28"), ids=("legacy", "modern"))
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, "Preview generation failed: no download URL returned"),
        (
            requests.ConnectionError(PRIVATE_DETAIL),
            "Could not generate the tax preview. Please try again.",
        ),
        (
            RuntimeError(PRIVATE_DETAIL),
            "Could not generate the tax preview. Please try again or contact Norman support.",
        ),
    ],
    ids=("missing-download-url", "upstream-error", "unexpected-error"),
)
def test_preview_error_is_useful_and_safe_on_wire(
    version, failure, expected, monkeypatch, tmp_path
):
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr("norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "oauth.json"))
    # Schedule restoration before create_app and lifespan replace these globals.
    monkeypatch.setattr(context, "oauth_provider", context.get_oauth_provider())
    monkeypatch.setattr(context, "_api_client", context.get_api_client())
    api = PreviewAPI(failure)

    @asynccontextmanager
    async def offline_lifespan(_):
        context.set_api_client(api)
        yield {"api": api}

    server = create_app(
        host="127.0.0.1",
        public_url="http://localhost:8000",
        transport="streamable-http",
        streamable_http_options={"stateless": True, "json_response": True},
    )
    server._lowlevel_server.lifespan = offline_lifespan
    server._token_verifier = PreviewVerifier()
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
        "Authorization": "Bearer preview-fixture-token",
    }
    params = {
        "name": "generate_finanzamt_preview",
        "arguments": {"report_id": "preview-fixture-report"},
    }
    if version == "2026-07-28":
        headers.update({"MCP-Method": "tools/call", "MCP-Name": params["name"]})
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": version,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    with TestClient(create_cors_app(server), base_url="http://localhost:8000") as client:
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": params,
            },
        )
    assert response.status_code == 200
    wire = response.json()
    assert "error" not in wire, wire
    assert wire["result"]["isError"] is True
    assert wire["result"]["content"][0]["text"].endswith(expected)
    assert PRIVATE_DETAIL not in response.text
    assert len(api.calls) == 1
