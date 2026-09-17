"""Shared MCP tests: keep this file identical in the API and standalone MCP repos."""

import asyncio
import re
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from norman_mcp.tools.invoices import register_invoice_tools


LINE = {
    "id": "8a972d81-d949-4ff4-badb-290d76fcda98",
    "name": "Design",
    "quantity": 1.5,
    "rate": 12550,
    "vatRate": 19,
    "description": "Custom artwork",
    "unit": "hours",
    "productId": "80a0a4ef-44c2-45e3-a76d-8151625be200",
    "companyCategory": "460ac89c-50ba-461a-9be4-4b7f1881996c",
    "discountPercent": 0,
    "itemPriceNet": 18825,
    "itemPriceGross": 22402,
    "itemVatAmount": 3577,
    "itemDiscountAmount": 0,
    "gtuCode": "GTU_12",
    "isSplitPayment": False,
    "discountNote": "Legacy description",
}
DESIGN = {
    "template": "sovereign",
    "version": 1,
    "logoSize": 75,
    "textSize": "large",
    "spacing": "compact",
    "tableBorders": "grid",
}
COMMON = {
    "client": "client-1",
    "invoicedItems": [LINE],
    "invoiceType": "SERVICES",
    "discountPercents": 0,
    "currency": "USD",
    "currencyExchanged": "EUR",
    "fullCostOriginExchanged": 224.02,
    "paymentTerms": "Net 14",
    "notes": "",
    "instructions": "Reference the invoice number",
    "message": "Thank you",
    "language": "de",
    "isVatIncluded": True,
    "iban": "DE89370400440532013000",
    "bic": "COBADEFFXXX",
    "bankName": "Commerzbank",
    "isToSend": False,
    "companyEmail": "billing@example.com",
    "createQr": True,
    "skipBankDetails": False,
    "saveClientDetails": False,
    "settingsOnOverdue": {
        "isToAutosendNotification": False,
        "notifyAfterDays": [3, 7],
        "notifyInParticularDays": [],
        "customEmailBody": "Please pay",
        "customEmailSubject": "Reminder",
    },
    "colorSchema": "#1E3A5F",
    "font": "Inter",
    "documentDesign": DESIGN,
    "mailingData": {
        "emailSubject": "Invoice",
        "emailBody": "Attached",
        "customClientEmail": "client@example.com",
        "additionalEmails": [],
        "isSendToCompany": False,
    },
    "clientData": {
        "name": "Client",
        "address": "Main Street 1",
        "city": "Berlin",
        "zipCode": "10115",
        "country": "DE",
        "vatNumber": "",
        "email": "client@example.com",
        "phone": "",
    },
    "companyData": {
        "name": "Studio",
        "currency": "EUR",
        "address": "Main Street 2",
        "zipCode": "10115",
        "city": "Berlin",
        "country": "DE",
        "taxState": "BE",
        "vatNumber": "DE123456789",
        "taxNumber": "123/456/78901",
        "iban": "",
        "bic": "",
        "bankName": "",
    },
    "taxExemptReason": "",
    "onlinePaymentEnabled": False,
    "sourceContract": "contract-1",
}
INVOICE = {
    **COMMON,
    "invoiceNumber": "MCP-1",
    "issued": "2026-09-17",
    "dueTo": "2026-10-01",
    "serviceStartDate": "2026-09-01",
    "serviceEndDate": "2026-09-15",
    "type": "invoice",
    "deliveryDate": "2026-09-17",
    "status": "draft",
    "paymentStatus": "unpaid",
    "paymentDate": "2026-09-17",
    "bankAccountPk": "bank-1",
    "isToCreateTransaction": False,
    "paidAmount": 0,
}
RECURRING = {
    **COMMON,
    "recurringNumber": "MCP-SERIES",
    "frequencyType": "monthly",
    "frequencyUnit": 2,
    "startsFromDate": "2026-10-01",
    "endsOnInvoiceCount": 5,
    "isOngoing": False,
    "paymentDueDays": 0,
    "billingInAdvance": True,
}


def arguments(payload):
    """Translate fixture API names to the existing public tool argument names."""
    names = {
        "client": "client_id",
        "invoicedItems": "items",
        "sourceContract": "source_contract_id",
        "type": "document_type",
        "recurringNumber": "invoice_number",
    }
    return {names.get(key, re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()): value for key, value in payload.items()}


class Api:
    company_id = "company-1"

    def __init__(self, result=None):
        self.requests = []
        self.result = {"publicId": "invoice-1"} if result is None else result

    def _make_request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.result

    async def arequest(self, method, url, **kwargs):
        return self._make_request(method, url, **kwargs)


@pytest.fixture
def server():
    mcp = FastMCP()
    register_invoice_tools(mcp)
    return mcp


def call(server, api, name, **kwargs):
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return asyncio.run(server._tool_manager._tools[name].run(kwargs, context=context))


@pytest.mark.parametrize(
    ("tool", "payload", "path"),
    [
        ("create_invoice", INVOICE, "invoices/"),
        ("create_recurring_invoice", RECURRING, "recurring-invoices/"),
    ],
)
def test_create_forwards_every_option_through_real_mcp_validation(server, tool, payload, path):
    api = Api()
    call(server, api, tool, **arguments(payload))
    assert api.requests == [
        ("POST", f"https://api.norman.finance/api/v1/companies/company-1/{path}", {"json_data": payload})
    ]


@pytest.mark.parametrize("template", ["heritage", "regent", "meridian", "horizon", "atelier", "epoque", "sovereign"])
@pytest.mark.parametrize("tool", ["create_invoice", "create_recurring_invoice"])
def test_partial_template_keeps_api_defaults(server, template, tool):
    payload = INVOICE if tool == "create_invoice" else RECURRING
    api = Api()
    call(server, api, tool, **arguments({**payload, "documentDesign": {"template": template}}))
    assert api.requests[-1][2]["json_data"]["documentDesign"] == {"template": template}


@pytest.mark.parametrize("tool", ["create_invoice", "create_recurring_invoice"])
def test_omitted_branding_inherits_and_does_not_send(server, tool):
    api = Api()
    kwargs = {
        "client_id": None,
        "items": [{"name": "Service", "quantity": 1, "rate": 1000, "vatRate": 19}],
        "invoice_number": "MCP-1",
    }
    if tool == "create_recurring_invoice":
        kwargs.update(frequency_type="monthly", frequency_unit=1, starts_from_date="2026-10-01", is_ongoing=True)
    call(server, api, tool, **kwargs)
    data = api.requests[-1][2]["json_data"]
    assert data["client"] is None
    assert data["isToSend"] is False
    assert (
        not {"colorSchema", "font", "documentDesign", "onlinePaymentEnabled", "companyId", "companyEmail"} & data.keys()
    )
    if tool == "create_recurring_invoice":
        assert (
            not {
                "invoiceNumber",
                "issued",
                "dueTo",
                "serviceStartDate",
                "serviceEndDate",
                "deliveryDate",
                "type",
                "isRecurring",
            }
            & data.keys()
        )
        assert not {"endsOnInvoiceCount", "endsOnDate"} & data.keys()


@pytest.mark.parametrize(
    ("tool", "id_arg", "path"),
    [
        ("update_invoice", "invoice_id", "invoices/"),
        ("update_recurring_invoice", "recurring_invoice_id", "recurring-invoices/"),
    ],
)
def test_patch_preserves_false_empty_zero_and_null_and_does_not_fill_defaults(server, tool, id_arg, path):
    api = Api()
    changes = {
        "sourceContract": None,
        "notes": "",
        "onlinePaymentEnabled": False,
        "discountPercents": 0,
        "settingsOnOverdue": None,
        "documentDesign": {"template": "atelier"},
        "invoicedItems": [LINE],
    }
    call(server, api, tool, **{id_arg: "document-1"}, changes=changes)
    assert api.requests == [
        ("PATCH", f"https://api.norman.finance/api/v1/companies/company-1/{path}document-1/", {"json_data": changes})
    ]


@pytest.mark.parametrize(
    "design",
    [
        {"template": "unknown"},
        {"template": "heritage", "version": 2},
        {"template": "regent", "logoSize": 24},
        {"template": "regent", "logoSize": 101},
        {"template": "regent", "spacing": "wide"},
        {"template": "regent", "textSize": None},
        {"template": "regent", "tableBorders": "round"},
        {"template": "regent", "watermark": True},
    ],
)
def test_invalid_design_never_reaches_api(server, design):
    api = Api()
    with pytest.raises(Exception, match="validation|Design controls"):
        call(server, api, "create_invoice", client_id="client-1", items=[LINE], document_design=design)
    assert api.requests == []


def test_unknown_invoice_and_line_fields_are_rejected(server):
    api = Api()
    for changes in ({"logoWidth": 900}, {"invoicedItems": [{**LINE, "unknown": 1}]}):
        with pytest.raises(Exception, match="Extra inputs"):
            call(server, api, "update_invoice", invoice_id="invoice-1", changes=changes)
    assert not api.requests


def test_settings_use_scoped_endpoint_and_sparse_patch(server):
    api = Api({"invoiceSettings": {"showCustomerNumber": True}})
    result = call(server, api, "get_invoice_settings")
    assert result == api.result
    changes = {"showContactPerson": False, "documentDesign": {"template": "epoque", "logoSize": 100}}
    call(server, api, "update_invoice_settings", changes=changes)
    assert [r[0] for r in api.requests] == ["GET", "PATCH"]
    assert all(r[1].endswith("/companies/company-1/invoices/settings/") for r in api.requests)
    assert api.requests[-1][2] == {"json_data": changes}


def test_catalog_and_api_denial_are_returned_without_fallback(server):
    api = Api({"templates": [{"id": "regent", "available": False}]})
    assert call(server, api, "list_invoice_templates") == api.result
    assert api.requests[-1][1].endswith("/invoices/document-templates/")
    denied = Api({"error": "A paid plan is required", "code": "invoice_template_requires_subscription"})
    assert (
        call(server, denied, "update_invoice", invoice_id="invoice-1", changes={"documentDesign": DESIGN})
        == denied.result
    )
    assert len(denied.requests) == 1


@pytest.mark.parametrize("tool", ["update_invoice_settings", "update_invoice", "update_recurring_invoice"])
def test_empty_patch_is_rejected(server, tool):
    api = Api()
    ids = {"update_invoice": {"invoice_id": "i"}, "update_recurring_invoice": {"recurring_invoice_id": "r"}}
    with pytest.raises(Exception, match="at least one"):
        call(server, api, tool, changes={}, **ids.get(tool, {}))
    assert not api.requests


def test_new_tools_require_an_active_company(server):
    api = Api()
    api.company_id = None
    with pytest.raises(Exception, match="No company"):
        call(server, api, "list_invoice_templates")
    assert not api.requests


def test_reminder_fee_and_explicit_empty_transaction_lines(server):
    api = Api()
    call(server, api, "send_invoice_overdue_reminder", invoice_id="invoice-1", fee=2.5)
    assert api.requests[-1][2]["json_data"] == {"isSendToCompany": False, "fee": 2.5}
    call(server, api, "link_transaction", invoice_id="invoice-1", transaction_id="txn-1", items=[])
    assert api.requests[-1][2]["json_data"] == {"transaction": "txn-1", "items": []}


def test_discovery_schema_advertises_controls_and_edit_fields(server):
    schemas = {tool.name: tool.inputSchema for tool in asyncio.run(server.list_tools())}
    schema = schemas["create_invoice"]
    design = schema["$defs"]["DocumentDesign"]["properties"]
    assert len(design["template"]["enum"]) == 7
    assert set(design) == {"template", "version", "logoSize", "textSize", "spacing", "tableBorders"}
    assert schema["$defs"]["InvoiceItem"]["additionalProperties"] is False
    assert "online_payment_enabled" in schema["properties"]
    assert "changes" in schemas["update_invoice"]["properties"]
