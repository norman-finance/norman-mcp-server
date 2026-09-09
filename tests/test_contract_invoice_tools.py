import asyncio
from types import SimpleNamespace

import pytest

from norman_mcp.tools.contracts import invoice_arguments_from_contract
from norman_mcp.tools.invoices import register_invoice_tools


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def register(function):
            self.tools[function.__name__] = function
            return function

        return register


class Api:
    company_id = "company-1"

    def __init__(self, result):
        self.result = result
        self.requests = []

    async def arequest(self, method, url, **kwargs):
        return self._make_request(method, url, **kwargs)

    def _make_request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.result


def call(name, api, **kwargs):
    registry = Registry()
    register_invoice_tools(registry)
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return asyncio.run(registry.tools[name](ctx, **kwargs))


@pytest.fixture
def proposal():
    return {
        "sourceContract": "contract-1",
        "draft": {
            "client": "client-1",
            "sourceContract": "contract-1",
            "currency": "EUR",
            "issued": "2026-10-01",
            "dueTo": "2026-10-15",
            "invoicedItems": [
                {"name": "Service", "quantity": "1.5", "rate": "1250.50", "vatRate": 19}
            ],
            "isRecurring": True,
            "isOngoing": True,
            "frequencyType": "monthly",
            "frequencyUnit": 1,
            "startsFromDate": "2026-10-01",
            "paymentDueDays": 14,
            "billingInAdvance": True,
        },
        "reviewNotes": ["Review recipient"],
    }


def test_prepare_does_not_create_and_returns_minor_unit_arguments(proposal):
    api = Api(proposal)
    result = call("prepare_invoice_from_contract", api, context_attachment_id="context-1")
    assert len(api.requests) == 1
    assert api.requests[0][1].endswith("/companies/company-1/invoices/contract-draft/")
    assert api.requests[0][2]["json_data"] == {"contextAttachmentId": "context-1"}
    assert result["invoiceCreated"] is False
    assert result["suggestedTool"] == "create_recurring_invoice"
    arguments = result["suggestedArguments"]
    assert arguments["items"][0]["rate"] == 125050
    assert arguments["items"][0]["quantity"] == 1.5
    assert arguments["source_contract_id"] == "contract-1"
    assert arguments["is_to_send"] is False
    assert arguments["payment_due_days"] == 14
    assert arguments["billing_in_advance"] is True


def test_reviewed_recurring_creation_keeps_contract_and_has_no_artificial_end(proposal):
    arguments = invoice_arguments_from_contract(proposal)
    api = Api({"publicId": "invoice-1"})
    call("create_recurring_invoice", api, invoice_number="2026-1", **arguments)
    data = api.requests[-1][2]["json_data"]
    assert data["invoicedItems"][0]["rate"] == 125050
    assert data["sourceContract"] == "contract-1"
    assert data["isOngoing"] is True
    assert data["paymentDueDays"] == 14
    assert data["billingInAdvance"] is True
    assert data["isToSend"] is False
    assert "endsOnInvoiceCount" not in data
    assert "endsOnDate" not in data


def test_one_off_arguments_are_accepted_by_create_invoice(proposal):
    proposal["draft"]["isRecurring"] = False
    api = Api({"publicId": "invoice-1"})
    call(
        "create_invoice", api, invoice_number="2026-1", **invoice_arguments_from_contract(proposal)
    )
    data = api.requests[-1][2]["json_data"]
    assert data["sourceContract"] == "contract-1"
    assert data["invoicedItems"][0]["rate"] == 125050


def test_prepare_requires_one_source_and_selected_company():
    api = Api({})
    assert "error" in call("prepare_invoice_from_contract", api)
    assert "error" in call(
        "prepare_invoice_from_contract", api, attachment_id="a", context_attachment_id="b"
    )
    assert "error" in call("prepare_invoice_from_contract", api, file_content_base64="eA==")
    assert not api.requests
    api.company_id = None
    assert "error" in call("prepare_invoice_from_contract", api, attachment_id="a")
    assert not api.requests


def test_cancel_stops_the_selected_series_through_the_company_endpoint():
    api = Api({"publicId": "series-1", "lifeCycleStatus": "cancelled"})
    result = call("cancel_recurring_invoice", api, recurring_invoice_id="series-1")
    assert result["lifeCycleStatus"] == "cancelled"
    assert api.requests == [(
        "POST",
        "https://api.norman.finance/api/v1/companies/company-1/recurring-invoices/series-1/cancel/",
        {},
    )]
