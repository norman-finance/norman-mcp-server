import asyncio
import inspect
from types import SimpleNamespace

from pydantic.fields import FieldInfo
from norman_mcp.tools.transactions import register_transaction_tools


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def decorate(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorate


class Api:
    company_id = "company-1"

    def __init__(self):
        self.requests = []

    async def arequest(self, method, url, **kwargs):
        self.requests.append((method, kwargs))
        if method == "GET":
            return {"amount": "102.00", "cashflowType": "EXPENSE", "isRefund": True}
        return {"ok": True}


def invoke(fn, api, **overrides):
    args = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name == "ctx":
            args[name] = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
        elif isinstance(p.default, FieldInfo):
            args[name] = p.default.default
        elif p.default is not inspect.Parameter.empty:
            args[name] = p.default
    args.update(overrides)
    return asyncio.run(fn(**args))


def test_create_and_edit_refund_keep_positive_payment_and_fee_without_rc():
    registry, api = Registry(), Api()
    register_transaction_tools(registry)
    items = [
        {"amount": "100.00", "vat_rate": 19, "tax_treatment": "THIRD_COUNTRY_SERVICE_REVERSE_CHARGE"},
        {"amount": "2.00", "vat_rate": 0, "tax_treatment": "DOMESTIC_NO_VAT", "professional_use_part": 0},
    ]
    invoke(registry.tools["create_transaction"], api, amount=102, description="Refund", cashflow_type="EXPENSE",
           supplier_country="OUTSIDE_EU", is_refund=True, items=items)
    payload = api.requests[-1][1]["json"] if "json" in api.requests[-1][1] else api.requests[-1][1]["json_data"]
    assert sum(row["amount"] for row in payload["items"]) == 102
    assert [row["amount"] for row in payload["items"]] == [100, 2]
    assert payload["items"][1]["taxTreatment"] == "DOMESTIC_NO_VAT"
    for index, row in enumerate(items):
        row["public_id"] = f"row-{index}"
    invoke(registry.tools["update_transaction"], api, transaction_id="txn-1", items=items)
    payload = api.requests[-1][1].get("json", api.requests[-1][1].get("json_data"))
    assert [row["amount"] for row in payload["items"]] == [100, 2]
    assert payload["items"][0]["publicId"] == "row-0"
    invoke(registry.tools["update_transaction"], api, transaction_id="txn-1", items=items, is_refund=False)
    payload = api.requests[-1][1].get("json", api.requests[-1][1].get("json_data"))
    assert [row["amount"] for row in payload["items"]] == [-100, -2]


def test_manual_actual_tax_correction_is_transmitted_without_rate_calculation():
    from norman_mcp.tools.accounting import register_accounting_tools
    registry, api = Registry(), Api()
    register_accounting_tools(registry)
    invoke(registry.tools["create_manual_ledger_entry"], api, booking_date="2025-02-12", debit_code="6855",
           credit_code="1400", amount=0.59, memo="Documented VAT correction", tax_treatment="DOMESTIC_INPUT_VAT",
           tax_country_scope="DOMESTIC", tax_role="VAT", tax_correction_reason="BOOKKEEPING_ERROR",
           input_tax_deduction_percent=100)
    payload = api.requests[-1][1].get("json", api.requests[-1][1].get("json_data"))
    assert payload["amount"] == 0.59
    assert payload["taxRole"] == "VAT"
    assert payload["taxCorrectionReason"] == "BOOKKEEPING_ERROR"
    assert "taxRate" not in payload
