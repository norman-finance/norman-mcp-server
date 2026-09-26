"""What NormanAPI returns for failed and non-JSON responses.

A 403 paywall used to reach the agent as a bare "Access forbidden" (the body
with its `code` was dropped), and a binary success such as the DATEV ZIP was
replaced with {"success": true} -- the file was silently lost.
"""

import json

import pytest
import requests

from norman_mcp.api.client import NormanAPI

URL = "https://api.norman.finance/api/v1/companies/company-1/invoices/inv-1/send/"


def _response(status, body=b"", content_type="application/json", headers=None, reason="Reason"):  # noqa: ANN001, ANN202
    response = requests.Response()
    response.status_code = status
    response.reason = reason
    response.url = URL
    response._content = body if isinstance(body, bytes) else json.dumps(body).encode()  # noqa: SLF001
    response.headers["Content-Type"] = content_type
    response.headers.update(headers or {})
    return response


@pytest.fixture
def respond(monkeypatch):  # noqa: ANN001, ANN201
    """Make the next API call answer with `answer` (a Response or an exception)."""

    def install(answer):  # noqa: ANN001, ANN202
        def fake_request(**_kwargs):  # noqa: ANN202
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(requests, "request", fake_request)

    return install


def _call(method="POST"):  # noqa: ANN001, ANN202
    api = NormanAPI(access_token="token", authenticate_on_init=False)
    return api._make_request(method, URL)  # noqa: SLF001


def test_a_paywall_403_keeps_the_api_reason_and_code(respond):  # noqa: ANN001
    body = {"detail": "Sending invoices by email is not included in your plan.", "code": "invoice_send_limit_reached"}
    respond(_response(403, body, reason="Forbidden"))

    assert _call() == {
        "error": "Sending invoices by email is not included in your plan.",
        "status_code": 403,
        "detail": body,
        "code": "invoice_send_limit_reached",
    }


def test_a_403_without_a_message_keeps_the_generic_explanation(respond):  # noqa: ANN001
    respond(_response(403, b"", content_type="text/html"))

    assert _call() == {"error": "Access forbidden. Check your account permissions.", "status_code": 403}


def test_a_404_keeps_the_body(respond):  # noqa: ANN001
    respond(_response(404, {"detail": "No Invoice matches the given query."}))

    result = _call("GET")
    assert result["status_code"] == 404
    assert result["error"] == "No Invoice matches the given query."
    assert result["detail"] == {"detail": "No Invoice matches the given query."}


def test_a_429_reports_when_to_retry(respond):  # noqa: ANN001
    respond(_response(429, {"detail": "Request was throttled."}, headers={"Retry-After": "30"}))

    result = _call()
    assert result["status_code"] == 429
    assert result["retry_after"] == "30"
    assert result["detail"] == {"detail": "Request was throttled."}


def test_a_validation_error_keeps_the_field_errors(respond):  # noqa: ANN001
    body = {"depreciationDate": ["Active assets cannot have a disposal date."]}
    respond(_response(400, body, reason="Bad Request"))

    assert _call() == {
        "error": "Request failed with HTTP 400 (Bad Request).",
        "status_code": 400,
        "detail": body,
    }


def test_a_proxy_error_page_is_trimmed(respond):  # noqa: ANN001
    page = b"<html><body>" + b"x" * 5000 + b"</body></html>"
    respond(_response(502, page, content_type="text/html", reason="Bad Gateway"))

    result = _call()
    assert result["error"] == "Request failed with HTTP 502 (Bad Gateway)."
    assert result["status_code"] == 502
    assert len(result["detail"]) == 2000


def test_a_binary_success_is_described_not_silently_dropped(respond):  # noqa: ANN001
    respond(_response(200, b"PK\x03\x04zip-bytes", content_type="application/zip"))

    result = _call()
    assert result["contentType"] == "application/zip"
    assert result["sizeBytes"] == len(b"PK\x03\x04zip-bytes")
    assert "download link" in result["message"]


@pytest.mark.parametrize("content_type", ["text/xml", "application/xml", "application/vnd.api+xml; charset=utf-8"])
def test_xml_comes_back_as_text(respond, content_type):  # noqa: ANN001
    respond(_response(200, b"<Invoice/>", content_type=content_type))

    assert _call("GET") == {"content": "<Invoice/>"}


@pytest.mark.parametrize("body", [[{"code": "skr03"}], "Tax number is valid", {"id": 1}])
def test_json_bodies_are_returned_as_sent(respond, body):  # noqa: ANN001
    respond(_response(200, body))

    assert _call("GET") == body


def test_an_empty_success_is_an_empty_object(respond):  # noqa: ANN001
    respond(_response(204, b""))

    assert _call("DELETE") == {}


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (requests.exceptions.ConnectionError("reset"), "connection_error"),
        (requests.exceptions.Timeout("slow"), "timeout"),
        (requests.exceptions.ChunkedEncodingError("broken"), "request_error"),
        (TypeError("Object of type datetime is not JSON serializable"), "unexpected_error"),
    ],
)
def test_transport_failures_carry_a_code(respond, exception, code):  # noqa: ANN001
    respond(exception)

    result = _call()
    assert result["code"] == code
    assert result["error"]
    assert "status_code" not in result
