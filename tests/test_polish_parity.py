"""Contract matrix shared with the embedded MCP; all records are synthetic."""

# Private SDK handlers and response bodies are intentional in protocol fixtures.
# ruff: noqa: SLF001, PLR2004
import asyncio
import inspect
from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from pydantic.fields import FieldInfo

from norman_mcp.bookkeeping_context import company_bookkeeping_context
from norman_mcp.tools import accounting, polish_accounting, tax_advisor, transactions
from norman_mcp.tools.invoice_schemas import InvoiceItem
from norman_mcp.tools.polish_assets import PolishAssetTax

ID = UUID("11111111-1111-4111-8111-111111111111")


class Registry:
    def __init__(self) -> None:
        self.functions = {}
        self.annotations = {}

    def tool(self, *args: Any, **kwargs: Any) -> Any:
        def register(fn: Any) -> Any:
            self.functions[fn.__name__] = fn
            self.annotations[fn.__name__] = kwargs.get("annotations")
            return fn

        return register

    def call(self, tool_name: Any, api: Any, **kwargs: Any) -> Any:
        fn = self.functions[tool_name]
        values = {
            k: p.default.default
            for k, p in inspect.signature(fn).parameters.items()
            if isinstance(p.default, FieldInfo) and not p.default.is_required()
        }
        values.update(kwargs)
        ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
        return asyncio.run(fn(ctx=ctx, **values))


class Api:
    company_id = "selected-company"

    def __init__(self, country: Any = "PL", chart: Any = "PL_FULL", response: Any = None) -> None:
        self.company = {
            "country": country,
            "currency": "PLN" if country == "PL" else "EUR",
            "chartOfAccounts": {"code": chart},
            "isSme": chart in {"PL_FULL", "skr04"},
            "usesCompanyChart": True,
        }
        self.requests = []
        self.response = response if response is not None else {"results": [], "next": "page-3"}

    def _make_request(self, method: Any, url: Any, **kwargs: Any) -> Any:
        self.requests.append((method, url, kwargs))
        return self.company if url.endswith("/companies/selected-company/") else self.response

    async def arequest(self, method: Any, url: Any, **kwargs: Any) -> Any:
        return self._make_request(method, url, **kwargs)


@pytest.mark.parametrize("code", ["23", "8", "5", "0", "np", "oo", "zw", ""])
def test_vat_code_survives_both_wire_models(code: Any) -> None:
    rate = int(code) if code.isdigit() else 0
    item = InvoiceItem(name="Synthetic service", quantity=1, rate=10000, vat_rate=rate, vat_code=code)
    assert item.payload()["vatCode"] == code
    assert transactions._build_items_payload([{"amount": 100, "vat_code": code}], negate=False)[0]["vatCode"] == code


def test_asset_schema_preserves_reviewed_values_and_does_not_invent_confirmations() -> None:
    tax = PolishAssetTax(
        kind="computer",
        entry_date="2026-10-01",
        annual_rate="30.00",
        method="linear",
        vat_rate=23,
        vat_recovery=100,
    )
    assert tax.payload()["entryDate"] == "2026-10-01"
    assert tax.payload()["annualRate"] == "30.00"
    assert "eligibilityConfirmed" not in tax.payload()
    with pytest.raises(ValidationError):
        PolishAssetTax(**(tax.model_dump() | {"vat_rate": 19}))
    registry = Registry()
    accounting.register_accounting_tools(registry)
    api = Api()
    registry.call(
        "create_asset",
        api,
        name="Synthetic computer",
        asset_type="tangible",
        acquisition_date="2026-09-20",
        depreciation_basis=12000,
        useful_lifetime_months=40,
        gross_purchase_price=14760,
        polish_tax=tax,
        bill_id="bill-1",
        opening_date="2027-01-01",
        opening_book_value=11100,
    )
    body = api.requests[-1][2]["json_data"]
    assert body["polishTax"] == tax.payload()
    assert body["bill"] == "bill-1"
    assert body["openingBookValue"] == 11100
    assert body["useProfessionalPart"] == 1
    assert "/companies/selected-company/" in api.requests[-1][1]


CASES = [
    ("get_polish_tax_book", {"year": 2026, "month": 9}, "PL_KPIR", "accounting/tax-book/", "GET"),
    (
        "get_polish_tax_book_operation",
        {"transaction_id": ID},
        "PL_KPIR",
        f"accounting/tax-book/operations/{ID}/",
        "GET",
    ),
    (
        "list_polish_ledger_journal",
        {"date_from": date(2026, 1, 1), "date_to": date(2026, 12, 31), "page": 2},
        "PL_FULL",
        "accounting/polish-ledger/journal/",
        "GET",
    ),
    ("get_polish_ledger_entry", {"entry_id": ID}, "PL_FULL", f"accounting/polish-ledger/journal/{ID}/", "GET"),
    ("list_polish_ledger_accounts", {}, "PL_FULL", "accounting/polish-ledger/accounts/", "GET"),
    (
        "get_polish_ledger_account",
        {"code": "130", "date_from": date(2026, 1, 1), "date_to": date(2026, 12, 31)},
        "PL_FULL",
        "accounting/polish-ledger/accounts/130/",
        "GET",
    ),
    (
        "get_polish_trial_balance",
        {"date_from": date(2026, 1, 1), "date_to": date(2026, 12, 31)},
        "PL_FULL",
        "accounting/polish-ledger/trial-balance/",
        "GET",
    ),
    ("list_polish_financial_statements", {}, "PL_FULL", "accounting/polish-statements/", "GET"),
    ("get_polish_financial_statement", {"statement_id": ID}, "PL_FULL", f"accounting/polish-statements/{ID}/", "GET"),
    (
        "preview_polish_accounting_export",
        {"date_from": date(2026, 1, 1), "date_to": date(2026, 12, 31), "export_format": "optima"},
        "PL_FULL",
        "accounting/polish-export/preview/",
        "POST",
    ),
    ("get_polish_jpk_register", {"report_id": ID}, "PL_FULL", f"taxes/reports/{ID}/jpk-register/", "GET"),
    ("get_polish_jpk_filing_status", {"report_id": ID}, "PL_FULL", f"taxes/reports/{ID}/jpk-filing/", "GET"),
    ("get_polish_pit_filing_status", {"report_id": ID}, "PL_KPIR", f"taxes/reports/{ID}/pit-filing/", "GET"),
    ("get_polish_tax_estimates", {"year": 2026, "month": 9}, "PL_KPIR", "polish-tax-estimates/", "GET"),
]


@pytest.mark.parametrize(("name", "args", "chart", "suffix", "method"), CASES)
def test_polish_tools_scope_every_route_and_keep_api_results(
    name: Any, args: Any, chart: Any, suffix: Any, method: Any,
) -> None:
    registry = Registry()
    polish_accounting.register_polish_accounting_tools(registry)
    api = Api(chart=chart)
    assert registry.call(name, api, **args) == api.response
    assert api.requests[-1][:2] == (method, api.requests[0][1] + suffix)
    assert all("/companies/selected-company/" in request[1] for request in api.requests)
    if "page" in args:
        assert api.requests[-1][2]["params"]["page"] == 2
    if name == "preview_polish_accounting_export":
        assert api.requests[-1][2]["json_data"]["export_format"] == "optima"


@pytest.mark.parametrize(("name", "args", "chart", "suffix", "method"), CASES)
@pytest.mark.parametrize("company_id", [None, "selected-company"])
def test_polish_tools_do_not_fall_back_to_german_or_missing_company(  # noqa: PLR0913 - parametrized matrix
    name: Any, args: Any, chart: Any, suffix: Any, method: Any, company_id: Any,
) -> None:
    registry = Registry()
    polish_accounting.register_polish_accounting_tools(registry)
    api = Api(country="DE", chart="skr04")
    api.company_id = company_id
    assert "error" in registry.call(name, api, **args)
    assert len(api.requests) == (1 if company_id else 0)


def test_full_books_tools_reject_jdg_and_keep_bare_list() -> None:
    registry = Registry()
    polish_accounting.register_polish_accounting_tools(registry)
    api = Api(chart="PL_KPIR")
    assert registry.call("list_polish_ledger_accounts", api)["code"] == "polish_full_books_required"
    api = Api(response=[{"code": "130"}])
    assert registry.call("list_polish_ledger_accounts", api) == {"results": [{"code": "130"}]}
    assert registry.annotations["get_polish_tax_book"].model_dump(by_alias=True)["readOnlyHint"] is False


@pytest.mark.parametrize(("country", "chart"), [("PL", "PL_FULL"), ("PL", "PL_KPIR"), ("DE", "skr04")])
def test_company_resource_does_not_invent_german_context(country: Any, chart: Any) -> None:
    text = company_bookkeeping_context(Api(country, chart).company)
    if country == "PL":
        assert "PLN" in text
        assert "DATEV" not in text
        assert "Soll-Versteuerung" not in text
        assert chart in text
    else:
        assert "EUR" in text
        assert "DATEV" in text


def test_advisor_tax_settings_use_requested_company_without_switching_active_company() -> None:
    registry = Registry()
    tax_advisor.register_tax_advisor_tools(registry)
    api = Api(response={"results": []})
    registry.call("get_tax_compliance_status", api, company_id="client-company")
    calls = [call for call in api.requests if "/tax-settings/" in call[1]]
    assert len(calls) == 1
    assert calls[0][2]["company_id"] == "client-company"
    assert api.company_id == "selected-company"
