"""Small contract fixes where a tool sent or read what the API does not use."""

import json

import pytest
import requests

from norman_mcp.api.client import NormanAPI
from tests.mcp_harness import FakeApi, call_tool, error_payload, structured


@pytest.mark.parametrize(("given", "sent"), [("private", "person"), ("person", "person"), ("business", "business")])
def test_client_types_are_sent_as_the_api_values(given, sent):  # noqa: ANN001
    api = FakeApi({"publicId": "client-1"})

    structured(call_tool("create_client", {"name": "Erika Mustermann", "client_type": given}, api))

    assert api.requests[-1][2]["json_data"]["clientType"] == sent


def test_an_unknown_client_type_is_refused():
    api = FakeApi({"publicId": "client-1"})

    result = call_tool("create_client", {"name": "X", "client_type": "company"}, api)

    assert result.isError
    assert api.requests == []


def test_incorporation_choices_come_back_as_writable_values():
    # The camelCase renderer rewrites the choice dict's keys.
    api = FakeApi({"within7Days": "Within 7 days", "within2Weeks": "Within 2 weeks", "flexible": "Flexible"})

    data = structured(call_tool("get_incorporation_choices", {"choice_type": "notarization-timeframes"}, api))

    assert data == {"within_7_days": "Within 7 days", "within_2_weeks": "Within 2 weeks", "flexible": "Flexible"}


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("send_invoice", {"invoice_id": "inv-1", "subject": "Invoice", "body": "Hello"}),
        ("send_invoice_overdue_reminder", {"invoice_id": "inv-1"}),
        ("send_offer", {"offer_id": "offer-1", "subject": "Quote", "body": "Hello"}),
    ],
)
def test_a_send_that_sent_nothing_is_not_reported_as_sent(tool, arguments):  # noqa: ANN001
    # 201 with an empty body: the sender skipped the email (no recipient).
    payload = error_payload(call_tool(tool, arguments, FakeApi({})))

    assert payload["code"] == "no_recipient"


def test_a_real_send_passes_through():
    sent = {"subject": "Invoice RE-1", "body": "...", "status": "sent"}

    arguments = {"invoice_id": "inv-1", "subject": "Invoice", "body": "Hello"}

    assert structured(call_tool("send_invoice", arguments, FakeApi(sent))) == sent


def test_attachment_preview_reads_the_extension_from_a_presigned_url(monkeypatch):  # noqa: ANN001
    presigned = "https://files.example/attachments/receipt.png?X-Amz-Signature=abc"

    def respond(_method, url, _kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/download/"):
            return {"url": presigned}
        return {"file": presigned, "fileName": None}

    image = requests.Response()
    image.status_code = 200
    image._content = b"not-really-a-png"  # noqa: SLF001
    monkeypatch.setattr(requests, "get", lambda url, timeout: image)

    result = call_tool("get_attachment_preview", {"attachment_id": "att-1"}, FakeApi(respond))

    assert not result.isError
    assert result.content[0].type == "image"
    assert json.loads(result.content[1].text)["fileName"] == "receipt.png"


def test_attachment_preview_reports_a_failed_lookup():
    missing = {"error": "Resource not found.", "status_code": 404}

    result = call_tool("get_attachment_preview", {"attachment_id": "att-1"}, FakeApi(missing))

    assert result.isError
    assert json.loads(result.content[0].text) == missing


@pytest.mark.parametrize(("method", "retry_advised"), [("GET", True), ("POST", False), ("PATCH", False)])
def test_a_timed_out_write_is_not_advertised_as_safe_to_retry(monkeypatch, method, retry_advised):  # noqa: ANN001
    def time_out(**_kwargs):  # noqa: ANN202
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(requests, "request", time_out)
    api = NormanAPI(access_token="token", authenticate_on_init=False)

    result = api._make_request(method, "https://api.norman.finance/api/v1/example/")  # noqa: SLF001

    assert result["code"] == "timeout"
    assert ("try again later" in result["error"]) is retry_advised
    assert result.get("timed_out") is (None if retry_advised else True)
