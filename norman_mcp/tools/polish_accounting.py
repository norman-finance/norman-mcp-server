"""Polish bookkeeping reads and previews. Calculations and permissions remain in the API."""

from datetime import date
from typing import Any, Literal
from urllib.parse import quote, urljoin
from uuid import UUID

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
SYNC_READ = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _chart(company: dict) -> str:
    chart = company.get("chartOfAccounts")
    return str(chart.get("code", "") if isinstance(chart, dict) else chart or "").upper()


async def _request(  # noqa: PLR0913 - scoped HTTP request options
    ctx: Context,
    suffix: str,
    *,
    books: str | None = None,
    method: str = "GET",
    params: dict | None = None,
    payload: dict | None = None,
) -> dict[str, Any]:
    api = ctx.request_context.lifespan_context["api"]
    # Capture once; a company switch must not move an in-flight call to another company.
    company_id = api.company_id
    if not company_id:
        return {"error": "Select a company first.", "code": "company_required"}
    base = urljoin(config.api_base_url, f"api/v1/companies/{quote(str(company_id), safe='')}/")
    company = await api.arequest("GET", base, company_id=company_id)
    if not isinstance(company, dict) or company.get("error"):
        return company if isinstance(company, dict) else {"error": "Company unavailable."}
    if company.get("country") != "PL":
        return {"error": "This tool requires a Polish company.", "code": "polish_company_required"}
    chart = _chart(company)
    if books == "PL_FULL" and chart != books:
        return {"error": "Select a Polish company using PL_FULL books.", "code": "polish_full_books_required"}
    if books == "PL_KPIR" and (company.get("isSme") or chart == "PL_FULL"):
        return {"error": "The tax book is for Polish sole proprietors (JDG).", "code": "polish_jdg_required"}
    result = await api.arequest(
        method,
        urljoin(base, suffix),
        params={k: v for k, v in (params or {}).items() if v is not None},
        json_data=payload,
        company_id=company_id,
    )
    return {"results": result} if isinstance(result, list) else result


def _period(start: date, end: date) -> dict:
    return {"date_from": start.isoformat(), "date_to": end.isoformat()}


def register_polish_accounting_tools(mcp: Any) -> None:  # noqa: C901 - one registration per API action
    @mcp.tool(title="Get Polish Tax Book (KPiR)", annotations=SYNC_READ)
    async def get_polish_tax_book(
        ctx: Context,
        year: int = Field(ge=2000, le=2100),
        month: int | None = Field(default=None, ge=1, le=12),
    ) -> dict[str, Any]:
        """Read a JDG tax book, totals and exclusion reasons. The API synchronizes derived
        entries and exchange differences before reading. Returns the selected year/month,
        not a paginated subset. Does not confirm entries or submit taxes.
        """
        return await _request(ctx, "accounting/tax-book/", books="PL_KPIR", params={"year": year, "month": month})

    @mcp.tool(title="Explain Polish Tax Book Operation", annotations=SYNC_READ)
    async def get_polish_tax_book_operation(ctx: Context, transaction_id: UUID) -> dict[str, Any]:
        """Explain whether an operation is in KPiR and why; synchronizes derived entries first."""
        return await _request(ctx, f"accounting/tax-book/operations/{transaction_id}/", books="PL_KPIR")

    @mcp.tool(title="List Polish Ledger Journal", annotations=READ)
    async def list_polish_ledger_journal(  # noqa: PLR0913 - API filters
        ctx: Context,
        date_from: date,
        date_to: date,
        page: int = Field(default=1, ge=1),
        page_size: int = Field(default=50, ge=1, le=100),
        search: str | None = None,
        account: str | None = None,
        asset_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Read PL_FULL postings. Follow pagination until all pages are read before reporting totals."""
        return await _request(
            ctx,
            "accounting/polish-ledger/journal/",
            books="PL_FULL",
            params={
                **_period(date_from, date_to),
                "page": page,
                "pageSize": page_size,
                "search": search,
                "account": account,
                "asset": str(asset_id) if asset_id else None,
            },
        )

    @mcp.tool(title="Get Polish Ledger Entry", annotations=READ)
    async def get_polish_ledger_entry(ctx: Context, entry_id: UUID) -> dict[str, Any]:
        """Read a Polish posting with its source and reversal information."""
        return await _request(ctx, f"accounting/polish-ledger/journal/{entry_id}/", books="PL_FULL")

    @mcp.tool(title="List Polish Ledger Accounts", annotations=READ)
    async def list_polish_ledger_accounts(ctx: Context) -> dict[str, Any]:
        """Read the complete active PL_FULL chart; use these codes rather than German SKR codes."""
        return await _request(ctx, "accounting/polish-ledger/accounts/", books="PL_FULL")

    @mcp.tool(title="Get Polish Account Sheet", annotations=READ)
    async def get_polish_ledger_account(  # noqa: PLR0913 - API filters
        ctx: Context,
        code: str,
        date_from: date,
        date_to: date,
        page: int = Field(default=1, ge=1),
        page_size: int = Field(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        """Read an account's opening/running balances and paginated entries; balances are not bank balances."""
        return await _request(
            ctx,
            f"accounting/polish-ledger/accounts/{quote(code, safe='')}/",
            books="PL_FULL",
            params={**_period(date_from, date_to), "page": page, "pageSize": page_size},
        )

    @mcp.tool(title="Get Polish Trial Balance", annotations=READ)
    async def get_polish_trial_balance(ctx: Context, date_from: date, date_to: date) -> dict[str, Any]:
        """Read the API's complete PL_FULL trial balance in PLN, including opening and closing balances."""
        return await _request(
            ctx,
            "accounting/polish-ledger/trial-balance/",
            books="PL_FULL",
            params=_period(date_from, date_to),
        )

    @mcp.tool(title="List Polish Financial Statements", annotations=READ)
    async def list_polish_financial_statements(ctx: Context) -> dict[str, Any]:
        """Read all prepared PL_FULL financial statements. A draft or closed year does not prove KRS filing."""
        return await _request(ctx, "accounting/polish-statements/", books="PL_FULL")

    @mcp.tool(title="Get Polish Financial Statement", annotations=READ)
    async def get_polish_financial_statement(ctx: Context, statement_id: UUID) -> dict[str, Any]:
        """Read the workbook, statutory lines, XML issues and notes for a Polish financial statement."""
        return await _request(ctx, f"accounting/polish-statements/{statement_id}/", books="PL_FULL")

    @mcp.tool(title="Preview Polish Accounting Export", annotations=READ)
    async def preview_polish_accounting_export(  # noqa: PLR0913 - API export options
        ctx: Context,
        date_from: date,
        date_to: date,
        export_format: Literal["general", "optima", "epp"] = "general",
        *,
        include_files: bool = False,
        optima_target_db: str = "KSIEG",
        optima_source_db: str = "NORMN",
        sales_register: str = "SPRZEDAŻ",
        purchase_register: str = "ZAKUP",
        epp_version: Literal["1.11", "1.12"] = "1.11",
    ) -> dict[str, Any]:
        """Preview export compatibility, blockers, warnings and snapshot. Does not download, post or file."""
        return await _request(
            ctx,
            "accounting/polish-export/preview/",
            method="POST",
            payload={
                **_period(date_from, date_to),
                "export_format": export_format,
                "include_files": include_files,
                "optima_target_db": optima_target_db,
                "optima_source_db": optima_source_db,
                "sales_register": sales_register,
                "purchase_register": purchase_register,
                "epp_version": epp_version,
            },
        )

    @mcp.tool(title="Get Polish JPK VAT Register", annotations=READ)
    async def get_polish_jpk_register(ctx: Context, report_id: UUID) -> dict[str, Any]:
        """Read sales/purchases, totals and exclusions from the JPK register; not proof of filing."""
        return await _request(ctx, f"taxes/reports/{report_id}/jpk-register/")

    @mcp.tool(title="Get Polish JPK Filing Status", annotations=READ)
    async def get_polish_jpk_filing_status(ctx: Context, report_id: UUID) -> dict[str, Any]:
        """Read available filing methods, sessions, MF status and UPO availability. Only confirmed
        acceptance and UPO prove success; XML preparation/download does not. Does not submit or sign.
        blockReason/blockMessage say why Norman cannot file for the owner now; subscription_required means
        the plan has no filing (JDG Pro and Sp. z o.o. Max file): relay blockMessage, never a generic error.
        warnings (sales_without_invoice, cash_method_sales, unreviewed_operations) never block filing.
        refusal (code, description, reference_number, sent_at) is MF's refusal of the period's latest return:
        quote MF's description and code as MF gave them, then point to the report page to fix and send again.
        """
        return await _request(ctx, f"taxes/reports/{report_id}/jpk-filing/")

    @mcp.tool(title="Get Polish PIT Filing Status", annotations=READ)
    async def get_polish_pit_filing_status(ctx: Context, report_id: UUID) -> dict[str, Any]:
        """Read PIT submission status and UPO availability; does not submit or sign."""
        return await _request(ctx, f"taxes/reports/{report_id}/pit-filing/")

    @mcp.tool(title="Get Polish Tax Estimates", annotations=SYNC_READ)
    async def get_polish_tax_estimates(
        ctx: Context,
        year: int = Field(ge=2000, le=2100),
        month: int = Field(ge=1, le=12),
    ) -> dict[str, Any]:
        """Read API-calculated PIT/ZUS or CIT estimates. May synchronize derived books;
        estimates are not filed returns and missing amounts must not be presented as zero.
        """
        return await _request(ctx, "polish-tax-estimates/", params={"year": year, "month": month})
