"""Tools report what the API actually did, and reach it with the caller's token."""

from typing import Any, Dict, List

import pytest

from norman_mcp.tools import documents
from tests.mcp_harness import FakeApi, call_tool, read_resource, structured

API_ERROR = {"error": "Resource not found", "status_code": 404}


# --- update_company_details ---------------------------------------------------


def test_activity_start_is_sent_as_an_iso_date():
    api = FakeApi({"publicId": "company-1", "activityStart": "2022-01-01"})

    data = structured(call_tool("update_company_details", {"activity_start": "2022-01-01"}, api))

    method, url, kwargs = api.requests[-1]
    assert method == "PATCH"
    assert url.endswith("/api/v1/companies/company-1/")
    assert kwargs["json_data"] == {"activityStart": "2022-01-01"}
    assert data["message"] == "Company updated successfully"


def test_a_failed_company_update_is_not_reported_as_success():
    api = FakeApi({"error": "Request failed: 400", "status_code": 400, "detail": {"activityStart": ["bad"]}})

    data = structured(call_tool("update_company_details", {"name": "Geitau 21"}, api))

    assert data["status_code"] == 400
    assert "message" not in data


# --- delete tools --------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [("delete_client", {"client_id": "client-1"}), ("delete_rule", {"rule_id": "rule-1"})],
)
def test_a_failed_delete_is_reported(tool, arguments):  # noqa: ANN001
    assert structured(call_tool(tool, arguments, FakeApi(API_ERROR))) == API_ERROR


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("delete_bill", {"bill_id": "bill-1"}, "Bill bill-1 deleted successfully."),
        ("delete_vendor", {"vendor_id": "vendor-1"}, "Vendor vendor-1 deleted successfully."),
    ],
)
def test_a_204_delete_says_so(tool, arguments, message):  # noqa: ANN001
    # The API client answers an empty 204 body with {}.
    assert structured(call_tool(tool, arguments, FakeApi({}))) == {"message": message}


# --- per-request auth (hosted OAuth has no static access_token) -----------------


def test_einvoice_xml_goes_through_the_api_client():
    api = FakeApi({"content": "<Invoice/>"})

    data = structured(call_tool("get_einvoice_xml", {"invoice_id": "inv-1"}, api))

    assert data == {"xml_content": "<Invoice/>"}
    assert api.requests[-1][1].endswith("/api/v1/companies/company-1/invoices/inv-1/xml/")


def test_einvoice_xml_failure_is_passed_on():
    assert structured(call_tool("get_einvoice_xml", {"invoice_id": "inv-1"}, FakeApi(API_ERROR))) == API_ERROR


def test_company_resource_uses_the_api_client():
    api = FakeApi({"name": "Geitau 21 GmbH", "isSme": True, "accountType": "gmbh", "chartOfAccounts": None})

    text = read_resource("company://current", api)

    assert text.startswith("# Geitau 21 GmbH")
    assert api.requests[-1][1].endswith("/api/v1/companies/company-1/")


def test_advisor_clients_resource_uses_the_api_client():
    api = FakeApi([{"name": "Client GmbH", "public_id": "client-co", "account_type": "gmbh"}])

    text = read_resource("tax-advisor-clients://list", api)

    assert "Client GmbH" in text
    assert api.requests[-1][1].endswith("/api/v1/tax-advisor/clients/")


# --- trigger_datev_export -----------------------------------------------------


def test_datev_export_asks_for_a_download_link_and_reads_the_chart_code():
    def respond(method, _url, _kwargs):  # noqa: ANN001, ANN202
        if method == "GET":
            # The company serializer renders the chart as an object.
            return {
                "datevAdvisorNumber": "1234",
                "datevClientNumber": "5678",
                "chartOfAccounts": {"publicId": "c-1", "name": "SKR03", "code": "skr03"},
            }
        return {"downloadUrl": "https://api.norman.finance/api/v1/dl/datev/", "expiresIn": 3600}

    api = FakeApi(respond)
    data = structured(
        call_tool("trigger_datev_export", {"date_from": "2025-01-01", "date_to": "2025-12-31"}, api)
    )

    assert data["downloadUrl"] == "https://api.norman.finance/api/v1/dl/datev/"
    payload = api.requests[-1][2]["json_data"]
    assert payload["skrVariant"] == "SKR03"
    assert payload["responseFormat"] == "download_url"


# --- upload_structured_attachments ---------------------------------------------


@pytest.fixture
def no_backoff(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(documents, "STRUCTURED_IMPORT_BACKOFF_SECONDS", 0)


def _import_api(answers: List[Dict[str, Any]]) -> FakeApi:
    queue = list(answers)

    def respond(_method, _url, _kwargs):  # noqa: ANN001, ANN202
        return queue.pop(0)

    return FakeApi(respond)


DOC = {"file_content_base64": "JVBERi0xLjQ=", "file_name": "r.pdf"}


def test_external_id_defaults_the_source_system(no_backoff):  # noqa: ANN001
    api = _import_api([{"publicId": "att-1", "created": True}])

    data = structured(call_tool("upload_structured_attachments", {"documents": [{**DOC, "external_id": "x-1"}]}, api))

    assert data["created"] == 1
    metadata = api.requests[-1][2]["json_data"]
    assert metadata == {"external_source": "mcp", "external_id": "x-1"}


def test_idempotent_documents_are_retried_after_a_server_error(no_backoff):  # noqa: ANN001
    api = _import_api(
        [
            {"error": "Request failed: 502", "status_code": 502},
            {"error": "Connection error. Please check your network connection."},
            {"publicId": "att-1", "created": True},
        ]
    )

    data = structured(call_tool("upload_structured_attachments", {"documents": [{**DOC, "external_id": "x-1"}]}, api))

    assert len(api.requests) == 3
    assert data["created"] == 1 and data["failed"] == 0


def test_documents_without_external_id_are_not_retried(no_backoff):  # noqa: ANN001
    api = _import_api([{"error": "Request failed: 502", "status_code": 502}])

    data = structured(call_tool("upload_structured_attachments", {"documents": [DOC]}, api))

    assert len(api.requests) == 1
    assert data["failed"] == 1


def test_validation_errors_are_not_retried(no_backoff):  # noqa: ANN001
    api = _import_api([{"error": "Request failed: 400", "status_code": 400, "detail": {"file": ["bad"]}}])

    data = structured(call_tool("upload_structured_attachments", {"documents": [{**DOC, "external_id": "x-1"}]}, api))

    assert len(api.requests) == 1
    assert data["failed"] == 1
