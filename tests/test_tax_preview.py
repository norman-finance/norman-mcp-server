"""Verify the MIME contract of the non-binding Finanzamt preview tool."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent

from norman_mcp.tools.taxes import register_tax_tools
from tests.mcp_harness import FakeApi, call_tool


@pytest.mark.parametrize(
    ("mime_type", "expected"),
    [("image/jpeg", "image/jpeg"), ("image/png", "image/png"), (None, "image/jpeg")],
)
def test_tax_preview_preserves_api_image_format(mime_type, expected):
    calls = []
    payload = {
        "previewImage": "cHJldmlldy1maXh0dXJl",
        "downloadUrl": "https://example.test/preview.pdf",
    }
    if mime_type is not None:
        payload["mimeType"] = mime_type

    def request(method, url):
        calls.append((method, url))
        return payload

    api = SimpleNamespace(_make_request=request, company_id="company-1")
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    server = MCPServer()
    register_tax_tools(server)
    tool = server._tool_manager._tools["generate_finanzamt_preview"]

    result = asyncio.run(tool.fn(context, "report-1"))

    assert isinstance(result.content[0], ImageContent)
    assert result.content[0].mime_type == expected
    assert result.content[0].data == payload["previewImage"]
    assert isinstance(result.content[1], TextContent)
    metadata = json.loads(result.content[1].text)
    assert metadata["downloadUrl"] == payload["downloadUrl"]
    assert "previewImage" not in metadata
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/api/v1/companies/company-1/taxes/reports/report-1/generate-preview-url/")


def test_tax_preview_without_thumbnail_still_returns_pdf_link():
    api = SimpleNamespace(
        _make_request=lambda *_: {"downloadUrl": "https://example.test/preview.pdf"},
        company_id="company-1",
    )
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    server = MCPServer()
    register_tax_tools(server)

    result = asyncio.run(
        server._tool_manager._tools["generate_finanzamt_preview"].fn(context, "report-1")
    )

    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text)["downloadUrl"] == "https://example.test/preview.pdf"


@pytest.mark.parametrize(
    ("report_id", "company_id", "message"),
    [
        ("   ", "company-1", "Invalid report ID"),
        ("report-1", None, "No company available. Please authenticate first."),
    ],
)
def test_tax_preview_validation_messages_survive_mcp_call(report_id, company_id, message):
    api = FakeApi(company_id=company_id)
    result = call_tool("generate_finanzamt_preview", {"report_id": report_id}, api)

    assert result.is_error
    assert message in result.content[0].text
    assert api.requests == []
