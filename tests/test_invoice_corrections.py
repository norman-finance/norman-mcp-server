"""Shared MCP tests: keep this file identical in the API and standalone MCP repos."""

import asyncio
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from norman_mcp.tools.invoice_management import register_invoice_management_tools
from norman_mcp.tools.invoices import register_invoice_tools

COMPANY = "https://api.norman.finance/api/v1/companies/company-1/"
LINE = {"name": "Design", "quantity": 1, "rate": 10000, "vatRate": 19, "unit": "hours"}


class Api:
    company_id = "company-1"

    def __init__(self, result=None):
        self.requests = []
        self.result = {"publicId": "document-2"} if result is None else result

    def _make_request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.result

    async def arequest(self, method, url, **kwargs):
        return self._make_request(method, url, **kwargs)


@pytest.fixture
def server():
    mcp = FastMCP()
    register_invoice_management_tools(mcp)
    return mcp


def call(server, api, name, **kwargs):
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return asyncio.run(server._tool_manager._tools[name].run(kwargs, context=context))


def test_cancel_invoice_posts_to_the_cancel_action_with_nothing_but_the_choices(server):
    api = Api()
    assert call(server, api, "cancel_invoice", invoice_id="inv-1") == api.result
    call(server, api, "cancel_invoice", invoice_id="inv 1", issued="2026-09-17", message="Storno")
    assert api.requests == [
        ("POST", COMPANY + "invoices/inv-1/cancel/", {"json_data": {}}),
        ("POST", COMPANY + "invoices/inv%201/cancel/", {"json_data": {"issued": "2026-09-17", "message": "Storno"}}),
    ]


def test_credit_note_is_issued_at_once_with_every_line_unless_told_otherwise(server):
    api = Api()
    call(server, api, "create_credit_note", invoice_id="inv-1")
    call(
        server,
        api,
        "create_credit_note",
        invoice_id="inv-1",
        items=[LINE],
        status="draft",
        issued="2026-09-17",
        message="Two hours were not worked.",
    )
    assert api.requests == [
        ("POST", COMPANY + "invoices/inv-1/credit-note/", {"json_data": {"status": "saved"}}),
        (
            "POST",
            COMPANY + "invoices/inv-1/credit-note/",
            {
                "json_data": {
                    "status": "draft",
                    "invoicedItems": [LINE],
                    "issued": "2026-09-17",
                    "message": "Two hours were not worked.",
                }
            },
        ),
    ]


def test_duplicate_posts_an_empty_body_to_the_duplicate_action(server):
    api = Api()
    assert call(server, api, "duplicate_invoice", document_id="inv-1") == api.result
    assert api.requests == [("POST", COMPANY + "invoices/inv-1/duplicate/", {"json_data": {}})]


def test_delivery_note_from_an_invoice_or_quote(server):
    api = Api()
    call(server, api, "create_delivery_note", document_id="quote-1")
    call(server, api, "create_delivery_note", document_id="inv-1", items=[LINE], delivery_date="2026-09-20")
    assert api.requests == [
        ("POST", COMPANY + "invoices/quote-1/delivery-note/", {"json_data": {"status": "saved"}}),
        (
            "POST",
            COMPANY + "invoices/inv-1/delivery-note/",
            {"json_data": {"status": "saved", "invoicedItems": [LINE], "deliveryDate": "2026-09-20"}},
        ),
    ]


@pytest.mark.parametrize("status", ["sent", "cancelled", ""])
def test_only_draft_or_saved_is_accepted(server, status):
    api = Api()
    with pytest.raises(Exception, match="validation|Input should be"):
        call(server, api, "create_credit_note", invoice_id="inv-1", status=status)
    assert not api.requests


def test_unknown_line_fields_never_reach_the_api(server):
    api = Api()
    with pytest.raises(Exception, match="Extra inputs"):
        call(server, api, "create_delivery_note", document_id="inv-1", items=[{**LINE, "pallets": 3}])
    assert not api.requests


@pytest.mark.parametrize("tool", ["cancel_invoice", "create_credit_note", "create_delivery_note", "duplicate_invoice"])
def test_correction_tools_require_an_active_company(server, tool):
    api = Api()
    api.company_id = None
    ids = {"create_delivery_note": {"document_id": "d"}, "duplicate_invoice": {"document_id": "d"}}
    with pytest.raises(Exception, match="No company"):
        call(server, api, tool, **ids.get(tool, {"invoice_id": "i"}))
    assert not api.requests


def test_list_invoices_filters_by_document_type():
    mcp = FastMCP()
    register_invoice_tools(mcp)
    api = Api({"results": []})
    call(mcp, api, "list_invoices", document_type="credit_note")
    (request,) = api.requests
    assert request[0] == "GET"
    assert request[1] == COMPANY + "invoices/"
    assert request[2]["params"] == {"limit": 100, "type": "credit_note"}


def test_create_invoice_leaves_the_currency_to_the_company_unless_told() -> None:
    mcp = FastMCP()
    register_invoice_tools(mcp)
    api = Api()
    call(mcp, api, "create_invoice", client_id="client-1", items=[LINE], invoice_number="RE-1")
    assert "currency" not in api.requests[-1][2]["json_data"]
    call(mcp, api, "create_invoice", client_id="client-1", items=[LINE], invoice_number="RE-2", currency="USD")
    assert api.requests[-1][2]["json_data"]["currency"] == "USD"
