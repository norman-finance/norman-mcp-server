"""Operational reads reject tombstones without publishing misleading totals."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from norman_mcp.api import client as client_module
from norman_mcp.api.active_records import enforce_active_records, is_deleted_record
from norman_mcp.api.client import NormanAPI
from norman_mcp.api.grant import GrantAPI


ORIGIN = "https://api.norman.finance"
COMPANY = "11111111-1111-4111-8111-111111111111"
RECORD = "22222222-2222-4222-8222-222222222222"
TRANSACTIONS = f"/api/v1/companies/{COMPANY}/accounting/transactions/"
INVOICES = f"/api/v1/companies/{COMPANY}/invoices/"
ATTACHMENTS = f"/api/v1/companies/{COMPANY}/attachments/"
MARKERS = [
    {"deletedAt": "2026-10-01T09:00:00Z"},
    {"deleted_at": "2026-10-01T09:00:00Z"},
    {"isDeleted": True},
    {"is_deleted": True},
]


@pytest.mark.parametrize("marker", MARKERS)
@pytest.mark.parametrize(
    "path", [TRANSACTIONS, "/api/v1/accounting/transactions/", INVOICES, ATTACHMENTS]
)
def test_deleted_pages_fail_closed_without_leaking_rows_or_stale_totals(path, marker):
    stale = {"publicId": RECORD, "description": "private tombstone", **marker}
    payload = {
        "count": 123,
        "results": [{"publicId": "active"}, stale],
        "next": "https://api.norman.finance/?page=2",
        "totalAmount": "9000.00",
    }
    result = enforce_active_records("GET", ORIGIN + path, payload)
    assert result == {
        "error": "Active records could not be verified. This section is unavailable.",
        "status": "unavailable",
    }
    assert payload["results"][1] is stale  # no destructive rewriting of shared source data


@pytest.mark.parametrize("path", [TRANSACTIONS, INVOICES, ATTACHMENTS])
def test_deleted_detail_is_not_found_without_exposing_the_record(path):
    result = enforce_active_records(
        "GET", ORIGIN + path + RECORD + "/?format=json", {"publicId": RECORD, "isDeleted": True}
    )
    assert result == {"error": "Resource not found", "status_code": 404}


@pytest.mark.parametrize("status", ["removed", "Removed", "REMOVED"])
def test_removed_invoice_status_is_a_tombstone_in_list_and_detail(status):
    invoice = {"publicId": RECORD, "status": status}
    assert enforce_active_records("GET", ORIGIN + INVOICES, [invoice])["status"] == "unavailable"
    assert (
        enforce_active_records("GET", ORIGIN + INVOICES + RECORD + "/", invoice)["status_code"]
        == 404
    )
    assert enforce_active_records("GET", ORIGIN + TRANSACTIONS, [invoice]) == [invoice]


def test_read_only_post_rule_preview_rejects_deleted_transaction_matches():
    result = enforce_active_records(
        "POST",
        ORIGIN + "/api/v1/accounting/rules/preview/",
        [{"publicId": RECORD, "isDeleted": True}],
    )
    assert result["status"] == "unavailable"
    assert "sampledFrom" not in result


@pytest.mark.parametrize("status", ["pending", "cancelled", "draft", "saved", "sent", "overdue"])
def test_business_statuses_and_arbitrary_metadata_do_not_hide_active_invoices(status):
    invoice = {
        "publicId": RECORD,
        "status": status,
        "isDeleted": False,
        "deletedAt": None,
        "metadata": {"isDeleted": True, "status": "removed"},
    }
    page = {"results": [invoice], "count": 1, "next": None}
    assert enforce_active_records("GET", ORIGIN + INVOICES, page) is page
    assert enforce_active_records("GET", ORIGIN + INVOICES + RECORD + "/", invoice) is invoice


@pytest.mark.parametrize(
    "record",
    [
        None,
        RECORD,
        {},
        {"deletedAt": ""},
        {"deleted_at": None},
        {"isDeleted": "false"},
        {"isDeleted": "true"},
        {"isDeleted": 1},
        {"isArchived": True},
        {"isActive": False},
    ],
)
def test_absence_archive_and_non_boolean_flags_are_not_deletion(record):
    assert not is_deleted_record(record)


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/companies/{COMPANY}/products/",
        "/api/v1/companies/",
        "/api/v1/accounting/company-categories/",
        f"/api/v1/companies/{COMPANY}/accounting/ledger/journal/",
        "/api/v1/accounting/rule-executions/",
        INVOICES + "email-settings/",
        INVOICES + "email-templates/",
        INVOICES + "settings/",
        TRANSACTIONS + "flat-rates/",
    ],
)
def test_other_resources_and_audit_history_are_unchanged(path):
    payload = {"results": [{"isDeleted": True, "status": "removed"}], "count": 1}
    assert enforce_active_records("GET", ORIGIN + path, payload) is payload


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_entity_mutation_results_are_not_rewritten(method):
    payload = {"publicId": RECORD, "isDeleted": True}
    assert enforce_active_records(method, ORIGIN + ATTACHMENTS + RECORD + "/", payload) is payload


@pytest.mark.parametrize("native_async", [False, True])
def test_normal_client_guards_both_sync_and_async_paths(monkeypatch, native_async):
    api = NormanAPI(authenticate_on_init=False, access_token="test-token", _env_company_id=COMPANY)
    response = Mock(content=b"json", status_code=200)
    response.json.return_value = {"results": [{"isDeleted": True}], "count": 1}
    transport = Mock(return_value=response)
    monkeypatch.setattr(client_module.requests, "request", transport)
    url = ORIGIN + TRANSACTIONS
    params = {"page": 3, "pageSize": 10}
    result = (
        asyncio.run(api.arequest("GET", url, params=params))
        if native_async
        else api._make_request("GET", url, params=params)
    )
    assert result["status"] == "unavailable"
    assert "results" not in result and "count" not in result
    assert transport.call_args.kwargs["params"] == params  # no unsupported delete filters


@pytest.mark.asyncio
async def test_grant_client_guards_background_inbox_reads_and_preserves_scope():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"results": [{"status": "Removed"}], "count": 1})

    provider = SimpleNamespace(get_norman_token=lambda token: "grant-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await GrantAPI(provider, "mcp-token", COMPANY, client=client).arequest(
            "GET", ORIGIN + INVOICES, params={"page_size": 1, "status": "overdue"}
        )
    assert result["status"] == "unavailable" and "count" not in result
    assert len(seen) == 1
    assert seen[0].headers["X-Company-Id"] == COMPANY
    assert dict(seen[0].url.params) == {"page_size": "1", "status": "overdue"}
