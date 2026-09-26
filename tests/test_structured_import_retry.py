"""Structured imports: source_system defaults and idempotent retries.

Large batch imports saw some documents fail with 500/502 under load. The API
makes a document with source_system + external_id idempotent, so those can be
sent again safely -- and the API needs source_system whenever external_id is set.
"""

import base64

import pytest

from norman_mcp.tools import documents
from tests.mcp_harness import FakeApi, call_tool, structured

CREATED = {"created": True, "document": {"publicId": "attachment-1"}}
BAD_GATEWAY = {"error": "Request failed with HTTP 502 (Bad Gateway).", "status_code": 502}


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):  # noqa: ANN001, ANN201
    sleeps = []

    async def record(delay):  # noqa: ANN001, ANN202
        sleeps.append(delay)

    monkeypatch.setattr(documents.asyncio, "sleep", record)
    return sleeps


def _document(**fields):  # noqa: ANN003, ANN202
    return {
        "file_content_base64": base64.b64encode(b"%PDF-1.4 test").decode(),
        "file_name": "invoice.pdf",
        **fields,
    }


def _answers(*responses):  # noqa: ANN002, ANN202
    """Answer successive import requests with `responses`, in order."""
    remaining = list(responses)

    def respond(_method, _url, kwargs):  # noqa: ANN001, ANN202
        # Every attempt must upload the whole file again.
        assert kwargs["files"]["file"].read() == b"%PDF-1.4 test"
        return remaining.pop(0)

    return FakeApi(respond)


def _import(api, *docs):  # noqa: ANN001, ANN002, ANN202
    return structured(call_tool("upload_structured_attachments", {"documents": list(docs)}, api))


def test_external_id_without_source_system_defaults_to_mcp():
    api = _answers(CREATED)

    result = _import(api, _document(external_id="invoice-123"))

    assert result["created"] == 1
    metadata = api.requests[-1][2]["json_data"]
    assert metadata["external_id"] == "invoice-123"
    assert metadata["external_source"] == "mcp"


def test_an_explicit_source_system_is_kept():
    api = _answers(CREATED)

    _import(api, _document(external_id="invoice-123", source_system="stereotrader"))

    assert api.requests[-1][2]["json_data"]["external_source"] == "stereotrader"


def test_an_idempotent_import_is_retried_after_a_server_error(no_backoff_sleep):  # noqa: ANN001
    api = _answers(BAD_GATEWAY, {"error": "Connection error.", "code": "connection_error"}, CREATED)

    result = _import(api, _document(external_id="invoice-123"))

    assert result["created"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["attempts"] == 3
    assert len(api.requests) == 3
    # Exponential backoff with jitter: ~1s, then ~2s.
    assert len(no_backoff_sleep) == 2
    assert 0.5 <= no_backoff_sleep[0] <= 1.5
    assert 1.0 <= no_backoff_sleep[1] <= 3.0


def test_retries_stop_after_three_attempts():
    api = _answers(BAD_GATEWAY, BAD_GATEWAY, BAD_GATEWAY)

    result = _import(api, _document(external_id="invoice-123"))

    assert result["failed"] == 1
    assert result["results"][0]["status_code"] == 502
    assert result["results"][0]["attempts"] == 3
    assert len(api.requests) == 3


def test_a_document_without_external_id_is_never_retried():
    api = _answers(BAD_GATEWAY)

    result = _import(api, _document())

    assert result["failed"] == 1
    assert "attempts" not in result["results"][0]
    assert len(api.requests) == 1
    assert "external_source" not in api.requests[-1][2]["json_data"]


def test_a_client_error_is_not_retried():
    invalid = {"error": "Request failed with HTTP 400 (Bad Request).", "status_code": 400, "detail": {"currency": ["Invalid"]}}
    api = _answers(invalid)

    result = _import(api, _document(external_id="invoice-123"))

    assert result["failed"] == 1
    assert len(api.requests) == 1


def test_one_failed_document_does_not_stop_the_batch():
    api = _answers(BAD_GATEWAY, CREATED)

    result = _import(api, _document(), _document(external_id="invoice-2"))

    assert result["total"] == 2
    assert result["failed"] == 1
    assert result["created"] == 1
