import pytest

from norman_mcp.files.upload import store_file
from norman_mcp.server import mcp
from tests.mcp_harness import FakeApi, call_tool, error_payload, structured

COMPANY = {
    "isSme": True,
    "country": "DE",
    "chartOfAccounts": {"code": "skr04"},
    "datevAdvisorNumber": "1234567",
    "datevClientNumber": "12345",
}
PERIOD = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


def test_default_sme_export_uses_ledger_and_retains_validation():
    api = FakeApi(
        lambda method, *_: (
            COMPANY
            if method == "GET"
            else {
                "downloadUrl": "https://example.test/download",
                "validation": {"valid": True, "warningCount": 1},
            }
        )
    )
    got = structured(call_tool("trigger_datev_export", PERIOD, api))
    method, url, kwargs = api.requests[-1]
    assert method == "POST"
    assert url.endswith("/companies/company-1/accounting/ledger/datev-export/")
    assert kwargs["json_data"]["kind"] == "journal"
    assert kwargs["json_data"]["includeDocuments"] is True
    assert kwargs["json_data"]["responseFormat"] == "download_url"
    assert "skrVariant" not in kwargs["json_data"]
    assert got["validation"]["warningCount"] == 1


def test_ledger_failure_never_falls_back_to_transactions():
    api = FakeApi(lambda method, *_: COMPANY if method == "GET" else {"error": "Preflight failed"})
    call_tool("trigger_datev_export", PERIOD, api)
    # Country applicability read, export configuration read, then exactly one export attempt.
    assert [method for method, *_ in api.requests] == ["GET", "GET", "POST"]
    assert api.requests[-1][1].endswith("/ledger/datev-export/")


def test_explicit_transactions_export_remains_available():
    api = FakeApi(lambda method, *_: COMPANY if method == "GET" else {"downloadUrl": "test"})
    call_tool("trigger_datev_export", {**PERIOD, "source": "transactions"}, api)
    assert api.requests[-1][1].endswith("/api/v1/accounting/datev-export/")


def test_ledger_rejects_chart_override_instead_of_silently_ignoring_it():
    api = FakeApi(COMPANY)
    call_tool("trigger_datev_export", {**PERIOD, "skr_variant": "SKR03"}, api)
    # Applicability and configuration reads; a rejected chart override never exports.
    assert [method for method, *_ in api.requests] == ["GET", "GET"]


def test_preflight_uses_saved_numbers_and_is_read_only():
    api = FakeApi(lambda method, *_: COMPANY if method == "GET" else {"valid": True})
    got = structured(call_tool("validate_ledger_datev_export", PERIOD, api))
    assert got["valid"]
    payload = api.requests[-1][2]["json_data"]
    assert payload["validateOnly"] is True
    assert payload["advisorNumber"] == "1234567"
    assert "responseFormat" not in payload
    assert mcp._tool_manager._tools["validate_ledger_datev_export"].annotations.read_only_hint


def test_reader_posts_uploaded_bytes_without_creating_accounting_records():
    data = b'"EXTF";700;21;"Buchungsstapel"'
    ref = store_file(data, "books.csv")

    def respond(method, url, kwargs):
        assert method == "POST"
        assert url.endswith("/companies/company-1/accounting/datev/read/")
        field, upload = kwargs["files"][0]
        assert field == "file"
        assert upload[0] == "books.csv"
        assert upload[1].read() == data
        assert kwargs["json_data"] == {"search": "RE-1", "page": 2, "page_size": 20}
        return {"results": [], "valid": True, "count": 0}

    api = FakeApi(respond)
    got = structured(
        call_tool(
            "read_datev_file", {"file_ref": ref, "search": "RE-1", "page": 2, "page_size": 20}, api
        )
    )
    assert got["valid"]
    assert len(api.requests) == 1
    assert api.requests[0][2]["files"][0][1][1].closed
    assert mcp._tool_manager._tools["read_datev_file"].annotations.read_only_hint


def test_reader_refuses_paths_expired_refs_invalid_limits_and_missing_company():
    for args in (
        {"file_ref": "/etc/passwd"},
        {"file_ref": "ref_expired"},
        {"file_ref": "ref_unused", "page_size": 101},
    ):
        api = FakeApi({})
        result = call_tool("read_datev_file", args, api)
        assert result.is_error or structured(result).get("error")
        assert not api.requests
    api = FakeApi({}, company_id=None)
    call_tool("read_datev_file", {"file_ref": "ref_unused"}, api)
    assert not api.requests


@pytest.mark.parametrize("tool", ["trigger_datev_export", "validate_ledger_datev_export"])
def test_german_datev_exports_reject_polish_company_before_domain_request(tool):
    api = FakeApi({**COMPANY, "country": "PL", "chartOfAccounts": {"code": "PL_FULL"}})
    result = call_tool(tool, PERIOD, api)
    assert error_payload(result)["code"] == "german_company_required"
    assert len(api.requests) == 1
    method, url, _ = api.requests[0]
    assert method == "GET"
    assert url.endswith("/companies/company-1/")
