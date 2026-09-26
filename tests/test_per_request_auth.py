"""Hosted OAuth: every API call must use the caller's own token.

`NormanAPI.access_token` is only set in single-tenant stdio mode. Code that
built its own request with it sent "Authorization: Bearer None" in the hosted
connector and always got 401. These paths now go through the API client, which
resolves the token per request.
"""

import pytest
import requests

from norman_mcp.api.client import NormanAPI
from norman_mcp import context
from tests.mcp_harness import FakeApi, call_tool, error_payload, read_resource, structured

COMPANY = {
    "publicId": "company-1",
    "name": "Example GmbH",
    "isSme": True,
    "accountType": "GmbH",
    "chartOfAccounts": {"publicId": "coa-1", "name": "SKR 04", "code": "skr04"},
}


def test_einvoice_xml_goes_through_the_api_client():
    api = FakeApi({"content": "<Invoice/>"})

    data = structured(call_tool("get_einvoice_xml", {"invoice_id": "inv-1"}, api))

    assert data == {"xml_content": "<Invoice/>"}
    method, url, _kwargs = api.requests[-1]
    assert method == "GET"
    assert url.endswith("/api/v1/companies/company-1/invoices/inv-1/xml/")


def test_einvoice_validation_errors_are_reported():
    problems = {"error": "Request failed with HTTP 400 (Bad Request).", "status_code": 400, "detail": [{"field": "client"}]}

    assert error_payload(call_tool("get_einvoice_xml", {"invoice_id": "inv-1"}, FakeApi(problems))) == problems


def test_company_resource_goes_through_the_api_client():
    api = FakeApi(COMPANY)

    text = read_resource("company://current", api)

    assert text.startswith("# Example GmbH")
    assert "SKR 04 (SKR04)" in text
    assert api.requests[-1][1].endswith("/api/v1/companies/company-1/")


def test_company_resource_reports_api_errors():
    text = read_resource("company://current", FakeApi({"error": "Resource not found.", "status_code": 404}))

    assert text == "Error getting company details: Resource not found."


def test_tax_advisor_clients_resource_goes_through_the_api_client():
    api = FakeApi([{"public_id": "company-1", "name": "Client GmbH", "account_type": "GmbH"}])

    text = read_resource("tax-advisor-clients://list", api)

    assert "Client GmbH" in text
    assert api.requests[-1][1].endswith("/api/v1/tax-advisor/clients/")


@pytest.fixture
def oauth_api(monkeypatch):  # noqa: ANN001, ANN201
    """A hosted-mode client: no instance token, the caller's token in context."""
    sent = []

    def fake_request(**kwargs):  # noqa: ANN202
        sent.append(kwargs["headers"]["Authorization"])
        response = requests.Response()
        response.status_code = 200
        response._content = b"<Invoice/>"  # noqa: SLF001
        response.headers["Content-Type"] = "text/xml"
        return response

    monkeypatch.setattr(requests, "request", fake_request)
    api = NormanAPI(authenticate_on_init=False)
    api.token_source = "oauth"
    monkeypatch.setattr(NormanAPI, "company_id", property(lambda _self: "company-1"))
    return api, sent


def test_hosted_mode_sends_the_request_scoped_token(oauth_api):  # noqa: ANN001
    api, sent = oauth_api
    context.set_api_token("caller-token")
    try:
        data = structured(call_tool("get_einvoice_xml", {"invoice_id": "inv-1"}, api))
    finally:
        context.set_api_token(None)

    assert api.access_token is None
    assert sent == ["Bearer caller-token"]
    assert data == {"xml_content": "<Invoice/>"}
