"""Attachment preview must not bypass unavailable/deleted detail lookups."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mcp.server.mcpserver import MCPServer

from norman_mcp.tools.documents import register_document_tools


@pytest.fixture
def preview():
    server = MCPServer()
    register_document_tools(server)
    return server._tool_manager._tools["get_attachment_preview"].fn


def call(preview, api):
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return asyncio.run(preview(ctx, attachment_id="attachment-1"))


@pytest.mark.parametrize("detail", [
    {"error": "Resource not found", "status_code": 404},
    {"error": "Access forbidden", "status_code": 403},
    {"error": "Connection error"},
    {"errors": {"attachment": "Unavailable"}},
    None,
    [],
    {},
])
def test_unavailable_detail_stops_before_requesting_download(preview, monkeypatch, detail):
    api = SimpleNamespace(company_id="company-1", _make_request=Mock(return_value=detail))
    download = Mock(side_effect=AssertionError("No file should be downloaded"))
    monkeypatch.setattr("norman_mcp.tools.documents.requests.get", download)

    result = call(preview, api)

    assert result.is_error is True
    assert len(result.content) == 1 and result.content[0].type == "text"
    payload = json.loads(result.content[0].text)
    if isinstance(detail, dict) and detail:
        assert payload == detail
    else:
        assert payload["error"] == "Attachment details unavailable."
    assert "downloadUrl" not in payload
    api._make_request.assert_called_once()
    assert api._make_request.call_args.args[1].endswith("/attachments/attachment-1/")
    download.assert_not_called()


def test_deleted_between_detail_and_download_is_an_error_not_an_empty_preview(preview, monkeypatch):
    api = SimpleNamespace(company_id="company-1", _make_request=Mock(side_effect=[
        {"publicId": "attachment-1", "file": "receipt.png", "fileName": "receipt.png"},
        {"error": "Resource not found", "status_code": 404},
    ]))
    download = Mock(side_effect=AssertionError("No file should be downloaded"))
    monkeypatch.setattr("norman_mcp.tools.documents.requests.get", download)

    result = call(preview, api)

    assert result.is_error is True
    assert json.loads(result.content[0].text) == {"error": "Resource not found", "status_code": 404}
    assert api._make_request.call_count == 2
    assert api._make_request.call_args.args[1].endswith("/attachments/attachment-1/download/")
    download.assert_not_called()


def test_active_pdf_keeps_the_existing_download_preview_contract(preview, monkeypatch):
    api = SimpleNamespace(company_id="company-1", _make_request=Mock(side_effect=[
        {"publicId": "attachment-1", "file": "receipt.pdf", "fileName": "Receipt.pdf"},
        {"url": "https://files.example.test/receipt.pdf"},
    ]))
    download = Mock(side_effect=AssertionError("PDF previews return the link without fetching it"))
    monkeypatch.setattr("norman_mcp.tools.documents.requests.get", download)

    result = call(preview, api)

    assert result.is_error is False
    assert json.loads(result.content[0].text) == {
        "attachmentId": "attachment-1",
        "fileName": "Receipt.pdf",
        "downloadUrl": "https://files.example.test/receipt.pdf",
        "note": "File is not an image; use downloadUrl to access it.",
    }
    assert api._make_request.call_count == 2
    download.assert_not_called()


@pytest.mark.parametrize("download_response", [{}, None, []])
def test_empty_or_malformed_download_response_does_not_claim_preview_success(
    preview, monkeypatch, download_response
):
    api = SimpleNamespace(company_id="company-1", _make_request=Mock(side_effect=[
        {"publicId": "attachment-1", "file": "receipt.pdf", "fileName": "receipt.pdf"},
        download_response,
    ]))
    download = Mock(side_effect=AssertionError("No file should be downloaded"))
    monkeypatch.setattr("norman_mcp.tools.documents.requests.get", download)

    result = call(preview, api)

    assert result.is_error is True
    assert json.loads(result.content[0].text) == {"error": "Attachment download unavailable."}
    assert api._make_request.call_count == 2
    download.assert_not_called()
