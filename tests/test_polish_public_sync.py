"""Internal/public parity through production MCP dispatch, with a synthetic API.

These verify the external contract, not deployment or actual bookkeeping effects.
"""

import asyncio

import pytest

from norman_mcp.server import mcp
from tests.mcp_harness import FakeApi, call_tool, error_payload, structured


JOB = "36f8d4ef-42bf-415f-b862-e25d35bce87a"
LINE = {"name": "Usługa", "quantity": 1, "rate": 10000, "vatRate": 23, "vatCode": "23"}
CARD = {
    "cardType": "tax_setting_change",
    "proposalId": "proposal-1",
    "status": "pending",
    "openUrl": "https://app.norman.finance/account?proposal=proposal-1",
}


def payload(result):
    return error_payload(result) if result.is_error else structured(result)


@pytest.mark.parametrize("rate", [None, "3", "8.5", "12", "12.5", "17"])
def test_ryczalt_saves_only_a_proposal_and_returns_owner_review(rate):
    api = FakeApi(lambda method, *_: {"country": "PL"} if method == "GET" else CARD)
    args = {"setting": "ryczalt_rate", "revenue_category": "700"}
    if rate is not None:
        args["lump_sum_rate"] = rate
    result = structured(call_tool("propose_tax_setting_change", args, api))
    writes = [(method, url, kw["json_data"]) for method, url, kw in api.requests if method != "GET"]
    expected = {"category": "700"}
    if rate is not None:
        expected["ryczaltRate"] = rate
    assert len(writes) == 1
    assert writes[0][0] == "POST"
    assert writes[0][1].endswith("/companies/company-1/tax-setting-proposals/")
    assert writes[0][2] == {"setting": "ryczalt_rate", "values": expected}
    assert result["openUrl"] == CARD["openUrl"]
    assert result["proposal"]["status"] == "pending"


@pytest.mark.parametrize("args", [
    {"setting": "ryczalt_rate", "revenue_category": "700", "lump_sum_rate": "9"},
    {"setting": "tax_form", "revenue_category": "700", "tax_form": "flat"},
])
def test_invalid_or_mixed_proposal_never_writes(args):
    api = FakeApi({"country": "PL"})
    result = call_tool("propose_tax_setting_change", args, api)
    assert result.is_error or "error" in structured(result)
    assert all(method == "GET" for method, *_ in api.requests)


def test_ryczalt_checks_the_selected_company_on_each_call():
    def respond(method, url, _kw):
        if method == "GET":
            return {"country": "PL" if "/pl-company/" in url else "DE"}
        return CARD

    api = FakeApi(respond, company_id="pl-company")
    args = {"setting": "ryczalt_rate", "revenue_category": "700", "lump_sum_rate": "12"}
    structured(call_tool("propose_tax_setting_change", args, api))
    api.company_id = "de-company"
    assert "error" in payload(call_tool("propose_tax_setting_change", args, api))
    assert not any(method != "GET" and "/de-company/" in url for method, url, _ in api.requests)


@pytest.mark.parametrize("linked", [None, False, True])
def test_attachment_metadata_search_is_bounded_and_does_not_fetch_files(linked):
    api = FakeApi({"results": [{"publicId": "doc-1", "file": "private.pdf"}], "next": "page-3"})
    args = {
        "search": "Allegro", "date_from": "2026-09-01", "date_to": "2026-09-30",
        "page": 2, "page_size": 10, "include_download_urls": False,
    }
    if linked is not None:
        args["linked"] = linked
    result = structured(call_tool("list_attachments", args, api))
    assert len(api.requests) == 1
    assert api.requests[0][1].endswith("/companies/company-1/attachments/")
    expected = {k: v for k, v in args.items() if k != "include_download_urls"}
    assert api.requests[0][2]["params"] == expected
    assert "downloadUrl" not in result["results"][0]
    assert result["next"] == "page-3"


def test_attachment_default_still_enriches_links_for_the_active_company():
    def respond(_method, url, _kw):
        if url.endswith("/download/"):
            return {"url": "https://files.example/receipt.pdf"}
        return {"results": [{"publicId": "doc-1", "file": "private.pdf"}]}

    api = FakeApi(respond, company_id="pl-company")
    result = structured(call_tool("list_attachments", {"file_name": "receipt"}, api))
    assert result["results"][0]["downloadUrl"] == "https://files.example/receipt.pdf"
    assert len(api.requests) == 2
    assert all("/companies/pl-company/attachments/" in url for _, url, _ in api.requests)
    assert api.requests[0][2]["params"] == {"file_name": "receipt", "page": 1, "page_size": 50}


def test_transaction_search_keeps_zero_bounds_and_combines_paging_with_filters():
    api = FakeApi({"results": [], "next": "page-3"})
    structured(call_tool("search_transactions", {
        "min_amount": 0, "max_amount": 0, "category": "Usługi",
        "limit": 10, "page": 2, "payment_type": "NOT_PAID", "source": "document",
        "no_receipt": True,
    }, api))
    assert api.requests[0][1].endswith("/companies/company-1/accounting/transactions/")
    assert api.requests[0][2]["params"] == {
        "minAmount": 0, "maxAmount": 0, "categoryName": "Usługi", "page_size": 10,
        "page": 2, "paymentType": "NOT_PAID", "source": "document", "noAttachment": True,
    }


@pytest.mark.parametrize("report_type", ["JPK_V7M", "CIT_8", "ADVANCED_SALEX_TAX"])
def test_report_filter_stays_company_scoped(report_type):
    api = FakeApi({"results": [], "next": None}, company_id="selected-company")
    structured(call_tool("list_tax_reports", {
        "date_from": "2026-01-01", "date_to": "2026-12-31", "report_type": report_type, "page": 2,
    }, api))
    assert "/companies/selected-company/" in api.requests[0][1]
    assert api.requests[0][2]["params"] == {
        "date_from": "2026-01-01", "date_to": "2026-12-31", "type": report_type, "page": 2,
    }


@pytest.mark.parametrize("args,sequence", [
    ({"document_type": "quote", "quote_kind": "proforma"}, "proforma"),
    ({"document_type": "quote", "quote_kind": "offer"}, "quote"),
    ({"document_type": "quote"}, "quote"),
    ({}, "invoice"),
])
def test_proforma_uses_its_own_sequence_and_keeps_quote_type(args, sequence):
    def respond(method, _url, kw):
        if method == "GET":
            return {"nextInvoiceNumber": "PF-1"}
        return {"publicId": "invoice-1", **kw["json_data"]}

    api = FakeApi(respond)
    result = structured(call_tool("create_invoice", {
        "client_id": "client-1", "items": [LINE], "currency": "PLN", "issued": "2026-10-01", **args,
    }, api))
    assert len(api.requests) == 2
    assert api.requests[0][2]["params"] == {"type": sequence}
    body = api.requests[1][2]["json_data"]
    assert body["type"] == args.get("document_type", "invoice")
    assert body.get("quoteKind") == args.get("quote_kind")
    assert body["invoiceNumber"] == "PF-1"
    assert body["currency"] == "PLN"
    assert body["invoicedItems"][0]["vatCode"] == "23"
    assert body["isToSend"] is False
    assert result["publicId"] == "invoice-1"


def test_proforma_explicit_number_skips_number_lookup_and_list_filters_subtype():
    api = FakeApi({"publicId": "invoice-1"})
    structured(call_tool("create_invoice", {
        "client_id": "client-1", "items": [LINE], "document_type": "quote",
        "quote_kind": "proforma", "invoice_number": "PF-EXPLICIT",
    }, api))
    assert len(api.requests) == 1
    assert api.requests[0][2]["json_data"]["invoiceNumber"] == "PF-EXPLICIT"
    structured(call_tool("list_invoices", {"document_type": "quote", "quote_kind": "proforma"}, api))
    assert api.requests[1][2]["params"]["type"] == "quote"
    assert api.requests[1][2]["params"]["quoteKind"] == "proforma"


def test_proforma_rejects_invoice_type_without_creating_anything():
    api = FakeApi({})
    assert "error" in payload(call_tool("create_invoice", {
        "client_id": "client-1", "items": [LINE], "quote_kind": "proforma",
    }, api))
    assert api.requests == []


def test_numbering_error_does_not_continue_creating_the_proforma():
    api = FakeApi({"error": "Numbering unavailable", "status_code": 503})
    result = payload(call_tool("create_invoice", {
        "client_id": "client-1", "items": [LINE], "document_type": "quote", "quote_kind": "proforma",
    }, api))
    assert "Numbering unavailable" in result["error"]
    assert len(api.requests) == 1 and api.requests[0][0] == "GET"


def test_csv_preview_and_confirmed_apply_pass_the_exact_batch_and_token():
    api = FakeApi({"previewToken": "signed-preview", "mutableCount": 2, "immutableCount": 1})
    structured(call_tool("list_csv_import_jobs", {"limit": 10}, api))
    assert api.requests[0][2]["params"] == {"limit": 10}
    preview = structured(call_tool("rollback_csv_import_transactions", {"csv_import_job_id": JOB}, api))
    assert api.requests[1][2]["json_data"] == {"dryRun": True, "confirmed": False}
    structured(call_tool("rollback_csv_import_transactions", {
        "csv_import_job_id": JOB, "dry_run": False, "confirmed": True,
        "preview_token": preview["previewToken"],
    }, api))
    assert api.requests[2][1].endswith(f"/companies/company-1/accounting/transactions/csv-imports/{JOB}/rollback/")
    assert api.requests[2][2]["json_data"] == {
        "dryRun": False, "confirmed": True, "previewToken": "signed-preview",
    }


@pytest.mark.parametrize("args", [{}, {"confirmed": True}, {"preview_token": "signed-preview"}])
def test_csv_apply_needs_both_confirmation_and_preview_token(args):
    api = FakeApi({})
    result = structured(call_tool("rollback_csv_import_transactions", {
        "csv_import_job_id": JOB, "dry_run": False, **args,
    }, api))
    assert result["confirmationRequired"] is True
    assert api.requests == []


def test_csv_stale_or_foreign_preview_error_is_not_hidden_or_retried():
    api = FakeApi({"error": "Preview expired or changed", "status_code": 409})
    result = payload(call_tool("rollback_csv_import_transactions", {
        "csv_import_job_id": JOB, "dry_run": False, "confirmed": True, "preview_token": "stale",
    }, api))
    assert result["status_code"] == 409
    assert len(api.requests) == 1


@pytest.mark.parametrize("currency", ["PLN", "EUR"])
def test_bill_can_be_recorded_without_a_bank_account_or_payment(currency):
    api = FakeApi({"publicId": "bill-1"})
    structured(call_tool("create_bill", {
        "vendor_name": "Synthetic Supplier", "amount": 123.45, "currency": currency,
        "reference": "FV-1", "due_date": "2026-11-01",
    }, api))
    assert len(api.requests) == 1
    method, url, kw = api.requests[0]
    assert method == "POST" and url.endswith("/accounting/bills/")
    assert kw["json_data"] == {
        "vendor_name": "Synthetic Supplier", "amount": "123.45", "currency": currency,
        "reference": "FV-1", "due_date": "2026-11-01", "status": "PENDING",
    }


def test_bill_scan_only_extracts_then_list_can_page_incoming_invoices():
    api = FakeApi({"vendor_name": "Synthetic Supplier", "amount": "123.45", "currency": "PLN"})
    result = structured(call_tool("scan_bill_document", {"attachment_id": "doc-1"}, api))
    assert result["currency"] == "PLN"
    assert len(api.requests) == 1
    assert api.requests[0][1].endswith("/accounting/bills/scan/")
    assert api.requests[0][2]["json_data"] == {"attachment_id": "doc-1"}
    structured(call_tool("list_bills", {"status": "PENDING", "limit": 10, "page": 2}, api))
    assert api.requests[1][2]["params"] == {"status": "PENDING", "page_size": 10, "page": 2}


def test_polish_bill_creation_does_not_enable_sepa_payments():
    api = FakeApi({"country": "PL"})
    assert "error" in payload(call_tool("pay_bill", {"bill_id": "bill-1", "account_id": "bank-1"}, api))
    assert all(method == "GET" for method, *_ in api.requests)


def test_reopened_workflow_step_never_advances():
    api = FakeApi({"publicId": "run-1", "state": "active"})
    structured(call_tool("complete_workflow_step", {"run_id": "run-1", "step": "review", "done": False}, api))
    assert len(api.requests) == 1
    assert api.requests[0][2]["json_data"] == {"step": "review", "done": False, "skipped": False}
    api.requests.clear()
    assert "error" in payload(call_tool("complete_workflow_step", {
        "run_id": "run-1", "step": "review", "done": False, "skipped": True,
    }, api))
    assert api.requests == []


def test_workflow_input_pauses_with_the_exact_question_without_advance():
    api = FakeApi({"publicId": "run-1", "blockedReason": "user_input"})
    structured(call_tool("request_workflow_input", {
        "run_id": "run-1", "step": "review", "question": "Czy to wszystkie dokumenty?",
    }, api))
    assert len(api.requests) == 1
    assert api.requests[0][1].endswith("/workflow-runs/run-1/step/")
    assert api.requests[0][2]["json_data"] == {
        "step": "review", "awaitInput": True, "question": "Czy to wszystkie dokumenty?",
    }


@pytest.mark.parametrize("action", ["confirm", "dismiss"])
def test_routine_decisions_only_update_the_selected_routine(action):
    api = FakeApi({"routines": [{"publicId": "routine-1", "kind": "monthly_invoice"}]})
    structured(call_tool("list_routines", {}, api))
    structured(call_tool(f"{action}_routine", {"routine_id": "routine-1"}, api))
    assert len(api.requests) == 2
    assert all(url.endswith("/assistant/routines/") for _, url, _ in api.requests)
    assert api.requests[1][2]["json_data"] == {"action": action, "routineId": "routine-1"}


NEW_TOOLS = [
    ("list_csv_import_jobs", {}),
    ("rollback_csv_import_transactions", {"csv_import_job_id": JOB}),
    ("create_bill", {"vendor_name": "Synthetic Supplier", "amount": 10, "currency": "PLN"}),
    ("scan_bill_document", {"attachment_id": "doc-1"}),
    ("request_workflow_input", {"run_id": "run-1", "step": "review", "question": "Ready?"}),
    ("list_routines", {}),
    ("confirm_routine", {"routine_id": "routine-1"}),
    ("dismiss_routine", {"routine_id": "routine-1"}),
]


@pytest.mark.parametrize("tool,args", NEW_TOOLS)
def test_new_tools_require_a_selected_company(tool, args):
    api = FakeApi({}, company_id=None)
    assert "No company" in payload(call_tool(tool, args, api))["error"]
    assert api.requests == []


@pytest.mark.parametrize("tool,args", NEW_TOOLS)
def test_new_tools_preserve_server_ownership_or_validation_errors(tool, args):
    api = FakeApi({"error": "Not found in selected company", "status_code": 404})
    result = payload(call_tool(tool, args, api))
    assert result["status_code"] == 404
    assert len(api.requests) == 1


@pytest.mark.parametrize("tool,args", [
    ("list_attachments", {"page": 0}),
    ("list_attachments", {"page_size": 101}),
    ("search_transactions", {"limit": 0}),
    ("search_transactions", {"page": -1}),
    ("list_tax_reports", {"page": 0}),
    ("list_bills", {"limit": 101}),
    ("list_csv_import_jobs", {"limit": 51}),
    ("rollback_csv_import_transactions", {"csv_import_job_id": "../other-company"}),
    ("create_bill", {"vendor_name": "Supplier", "amount": 10}),
    ("create_bill", {"vendor_name": "Supplier", "amount": 10, "currency": ""}),
    ("request_workflow_input", {"run_id": "run-1", "step": "review", "question": ""}),
])
def test_invalid_new_arguments_fail_before_any_api_call(tool, args):
    api = FakeApi({})
    assert call_tool(tool, args, api).is_error
    assert api.requests == []


def test_new_tools_publish_accurate_annotations_without_duplicate_aliases():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert {name for name, _ in NEW_TOOLS} <= tools.keys()
    assert tools["create_bill"].annotations.read_only_hint is False
    assert tools["create_bill"].annotations.idempotent_hint is False
    assert tools["rollback_csv_import_transactions"].annotations.destructive_hint is True
    assert tools["scan_bill_document"].annotations.read_only_hint is True
    assert tools["scan_bill_document"].annotations.open_world_hint is True
    assert not {"abandon_workflow", "schedule_monthly_workflow", "get_agent_digest"} & tools.keys()
    assert {"stop_workflow", "schedule_workflow", "get_agent_week"} <= tools.keys()
