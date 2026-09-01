import asyncio
import inspect
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from norman_mcp.files.upload import store_file
from norman_mcp.tools.accounting import register_accounting_tools


class FakeMcp:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(
        self, *args: Any, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        del args, kwargs

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[function.__name__] = function
            return function

        return register


class FakeApi:
    company_id = "company-1"

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    async def arequest(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.requests.append((method, url, kwargs))
        return {"ok": True}


def context_for(api: FakeApi) -> SimpleNamespace:
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context={"api": api})
    )


def registered_tools() -> tuple[FakeMcp, FakeApi]:
    mcp = FakeMcp()
    api = FakeApi()
    register_accounting_tools(mcp)
    return mcp, api


def test_accounting_workspace_registers_safe_parity_without_binding_submission() -> (
    None
):
    mcp, _api = registered_tools()

    assert {
        "analyze_accounting_cutover_documents",
        "preview_accounting_cutover",
        "apply_accounting_cutover",
        "list_chart_of_accounts",
        "create_chart_of_accounts_account",
        "list_assets",
        "list_ledger_journal",
        "get_ledger_profit_and_loss",
        "get_ledger_balance_sheet",
        "create_manual_ledger_entry",
        "list_annual_closes",
        "create_annual_close",
        "get_annual_close",
        "create_annual_close_entry",
        "get_annual_close_workbook",
    }.issubset(mcp.tools)
    assert not {name for name in mcp.tools if "submit" in name or "lock" in name}


def test_cutover_analysis_sends_repeated_multipart_file_fields() -> None:
    mcp, api = registered_tools()
    first_ref = store_file(b"first", "DTVF_Buchungsstapel_1.csv")
    second_ref = store_file(b"second", "DTVF_Buchungsstapel_2.csv")

    result = asyncio.run(
        mcp.tools["analyze_accounting_cutover_documents"](
            context_for(api),
            file_refs=[first_ref, second_ref],
        )
    )

    assert result == {"ok": True}
    method, url, kwargs = api.requests[-1]
    assert method == "POST"
    assert url.endswith("/accounting/cutover/analyze/")
    assert [field for field, _upload in kwargs["files"]] == ["files", "files"]
    assert [upload[0] for _field, upload in kwargs["files"]] == [
        "DTVF_Buchungsstapel_1.csv",
        "DTVF_Buchungsstapel_2.csv",
    ]
    assert all(upload[1].closed for _field, upload in kwargs["files"])


def test_cutover_analysis_rejects_expired_file_reference_without_request() -> None:
    mcp, api = registered_tools()

    result = asyncio.run(
        mcp.tools["analyze_accounting_cutover_documents"](
            context_for(api),
            file_refs=["ref_expired"],
        )
    )

    assert "expired" in result["error"]
    assert api.requests == []


def test_cutover_manual_preview_is_read_only_json_request() -> None:
    mcp, api = registered_tools()
    balances = [
        {
            "account_code": "1200",
            "side": "debit",
            "amount": "100.00",
            "memo": "Bank",
        }
    ]

    result = asyncio.run(
        mcp.tools["preview_accounting_cutover"](
            context_for(api),
            mode="year_start",
            fiscal_year_begin="2026-01-01",
            fiscal_year_end="2026-12-31",
            cutover_date="2026-01-01",
            opening_method="manual",
            opening_file_ref=None,
            booking_file_refs=None,
            parties_file_ref=None,
            assets_file_ref=None,
            manual_balance_date="2025-12-31",
            manual_balances=balances,
        )
    )

    assert result == {"ok": True}
    method, url, kwargs = api.requests[-1]
    assert method == "POST"
    assert url.endswith("/accounting/cutover/preview/")
    assert kwargs["files"] is None
    assert kwargs["json_data"] == {
        "mode": "year_start",
        "opening_method": "manual",
        "fiscal_year_begin": "2026-01-01",
        "fiscal_year_end": "2026-12-31",
        "cutover_date": "2026-01-01",
        "manual_balance_date": "2025-12-31",
        "manual_balances": balances,
    }


def test_cutover_preview_serializes_manual_balances_with_supporting_file() -> None:
    mcp, api = registered_tools()
    parties_ref = store_file(b"parties", "customers-and-vendors.csv")
    balances = [{"account_code": "1200", "side": "debit", "amount": "1.00"}]

    asyncio.run(
        mcp.tools["preview_accounting_cutover"](
            context_for(api),
            mode="year_start",
            fiscal_year_begin="2026-01-01",
            fiscal_year_end="2026-12-31",
            cutover_date="2026-01-01",
            opening_method="manual",
            opening_file_ref=None,
            booking_file_refs=None,
            parties_file_ref=parties_ref,
            assets_file_ref=None,
            manual_balance_date="2025-12-31",
            manual_balances=balances,
        )
    )

    _method, _url, kwargs = api.requests[-1]
    assert [field for field, _upload in kwargs["files"]] == ["parties_file"]
    assert json.loads(kwargs["json_data"]["manual_balances"]) == balances


def test_cutover_apply_requires_confirmation_then_posts_exact_payload() -> None:
    mcp, api = registered_tools()
    context = context_for(api)
    arguments = {
        "mode": "year_start",
        "fiscal_year_begin": "2026-01-01",
        "fiscal_year_end": "2026-12-31",
        "cutover_date": "2026-01-01",
        "opening_method": "manual",
        "opening_file_ref": None,
        "booking_file_refs": None,
        "parties_file_ref": None,
        "assets_file_ref": None,
        "manual_balance_date": "2025-12-31",
        "manual_balances": [{"account_code": "1200", "side": "debit", "amount": "100.00"}],
    }

    warning = asyncio.run(
        mcp.tools["apply_accounting_cutover"](
            context,
            confirmed=False,
            **arguments,
        )
    )
    assert warning["confirmationRequired"] is True
    assert api.requests == []

    result = asyncio.run(
        mcp.tools["apply_accounting_cutover"](
            context,
            confirmed=True,
            **arguments,
        )
    )

    assert result == {"ok": True}
    method, url, kwargs = api.requests[-1]
    assert method == "POST"
    assert url.endswith("/accounting/cutover/import/")
    assert kwargs["json_data"]["manual_balances"] == arguments["manual_balances"]


def test_annual_close_creation_is_draft_only() -> None:
    mcp, api = registered_tools()

    asyncio.run(
        mcp.tools["create_annual_close"](
            context_for(api),
            fiscal_year_begin="2026-01-01",
            fiscal_year_end="2026-12-31",
        ),
    )

    method, url, kwargs = api.requests[-1]
    assert method == "POST"
    assert url.endswith("/api/v1/companies/company-1/accounting/annual-closes/")
    assert kwargs["json_data"] == {
        "fiscalYearBegin": "2026-01-01",
        "fiscalYearEnd": "2026-12-31",
    }


def test_ledger_journal_declares_newest_first_as_its_default() -> None:
    mcp, _api = registered_tools()

    ordering = (
        inspect.signature(mcp.tools["list_ledger_journal"])
        .parameters["ordering"]
        .default
    )

    assert ordering.default == "date_desc"


def test_framework_switch_requires_confirmation_and_forwards_ui_guard() -> None:
    mcp, api = registered_tools()
    context = context_for(api)

    warning = asyncio.run(
        mcp.tools["switch_account_framework"](
            context,
            framework_code="skr04",
            confirmed=False,
        ),
    )
    result = asyncio.run(
        mcp.tools["switch_account_framework"](
            context,
            framework_code="skr04",
            confirmed=True,
        ),
    )

    assert warning["confirmationRequired"] is True
    assert result == {"ok": True}
    assert len(api.requests) == 1
    method, url, kwargs = api.requests[0]
    assert method == "PATCH"
    assert url.endswith("/api/v1/companies/company-1/")
    assert kwargs["json_data"] == {
        "chartOfAccounts": "skr04",
        "confirmChartOfAccountsSwitch": True,
    }


def test_asset_business_use_percent_is_converted_to_model_fraction() -> None:
    mcp, api = registered_tools()

    asyncio.run(
        mcp.tools["create_asset"](
            context_for(api),
            name="Mac Studio",
            asset_type="tangible",
            acquisition_date="2026-08-28",
            depreciation_basis=1000,
            useful_lifetime_months=36,
            gross_purchase_price=1190,
            business_use_percent=80,
            ledger_account_code="0670",
            transaction_id=None,
            transaction_item_id=None,
        ),
    )

    method, url, kwargs = api.requests[-1]
    assert method == "POST"
    assert url.endswith("/api/v1/companies/company-1/accounting/assets/")
    assert kwargs["json_data"]["useProfessionalPart"] == 0.8


def test_storno_requires_confirmation() -> None:
    mcp, api = registered_tools()
    context = context_for(api)

    warning = asyncio.run(
        mcp.tools["reverse_manual_ledger_entry"](
            context,
            entry_id="entry-1",
            confirmed=False,
            booking_date=None,
            memo="",
        ),
    )

    assert warning["confirmationRequired"] is True
    assert api.requests == []
