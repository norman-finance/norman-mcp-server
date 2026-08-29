"""MCP tools for Norman's SME Accounting workspace.

The UI, internal assistant and public MCP connector must all use the same REST
endpoints.  This module deliberately contains no accounting calculations: the
Ledger remains the source of truth and the API remains the only writer.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


def _api_and_company(
    ctx: Context,
) -> tuple[Any, Optional[str], Optional[Dict[str, Any]]]:
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    if not company_id:
        return (
            api,
            None,
            {
                "error": "No company available. Please authenticate and select a company first."
            },
        )
    return api, company_id, None


async def _request(
    api: Any,
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Use the non-blocking client in both the embedded and standalone MCP."""
    return await api.arequest(method, url, params=params, json_data=json_data)


def _company_url(company_id: str, suffix: str) -> str:
    return urljoin(
        config.api_base_url, f"api/v1/companies/{company_id}/{suffix.lstrip('/')}"
    )


def _compact(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def register_accounting_tools(mcp: Any) -> None:
    """Register Assets, Ledger, Chart of Accounts and year setup tools."""

    @mcp.tool(title="Get Accounting Setup", annotations=READ_ONLY)
    async def get_accounting_setup(
        ctx: Context,
        fiscal_year_begin: str = Field(
            description="Fiscal-year start in YYYY-MM-DD format"
        ),
        fiscal_year_end: str = Field(
            description="Fiscal-year end in YYYY-MM-DD format"
        ),
    ) -> Dict[str, Any]:
        """Get opening/cutover status for a fiscal year without changing the books."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        url = _company_url(company_id, "accounting/cutover/")
        return await _request(
            api,
            "GET",
            url,
            params={
                "fiscalYearBegin": fiscal_year_begin,
                "fiscalYearEnd": fiscal_year_end,
            },
        )

    @mcp.tool(title="List Chart of Accounts Templates", annotations=READ_ONLY)
    async def list_chart_of_accounts_templates(ctx: Context) -> Dict[str, Any]:
        """List account frameworks available for the selected company and country."""
        api, _company_id, error = _api_and_company(ctx)
        if error:
            return error
        url = urljoin(
            config.api_base_url, "api/v1/accounting/company-categories/templates/"
        )
        return await _request(api, "GET", url)

    @mcp.tool(title="List Chart of Accounts", annotations=READ_ONLY)
    async def list_chart_of_accounts(
        ctx: Context,
        search: Optional[str] = Field(
            default=None, description="Search account code or localized name"
        ),
        code: Optional[str] = Field(default=None, description="Exact account code"),
        account_type: Optional[str] = Field(
            default=None,
            description="ASSET, LIABILITY, EQUITY, INCOME or EXPENSE",
        ),
        availability: Optional[str] = Field(
            default=None,
            description="TRANSACTIONS or LEDGER_ONLY",
        ),
        status: Optional[str] = Field(
            default="ACTIVE", description="ACTIVE or INACTIVE"
        ),
        origin: Optional[str] = Field(default=None, description="SYSTEM or CUSTOM"),
        ordering: str = Field(
            default="code",
            description="code, -code, name, -name, accountType or -accountType",
        ),
        page: int = Field(default=1, ge=1),
        page_size: int = Field(default=50, ge=1, le=200),
    ) -> Dict[str, Any]:
        """Search and page through the selected company's complete account master."""
        api, _company_id, error = _api_and_company(ctx)
        if error:
            return error
        url = urljoin(config.api_base_url, "api/v1/accounting/company-categories/")
        params = _compact(
            {
                "search": search,
                "code": code,
                "accountType": account_type,
                "availability": availability,
                "status": status,
                "origin": origin,
                "ordering": ordering,
                "page": page,
                "pageSize": page_size,
                "includeInactive": status == "INACTIVE",
                "includeStatementOnly": True,
            }
        )
        return await _request(api, "GET", url, params=params)

    @mcp.tool(title="Create Chart of Accounts Account", annotations=WRITE)
    async def create_chart_of_accounts_account(
        ctx: Context,
        code: str = Field(description="Unique account code in the selected framework"),
        name: str = Field(description="User-facing account name"),
        account_type: str = Field(
            description="ASSET, LIABILITY, EQUITY, INCOME or EXPENSE"
        ),
        available_in_transactions: bool = Field(
            default=False,
            description="Whether this account may also be assigned to day-to-day Transactions",
        ),
        description: str = Field(
            default="", description="Optional accounting purpose or usage note"
        ),
        vat_applicable: bool = Field(default=False),
        suggested_vat_rate: int = Field(default=0, ge=0, le=100),
    ) -> Dict[str, Any]:
        """Create a custom Ledger account; balance-sheet accounts stay Ledger-only."""
        api, _company_id, error = _api_and_company(ctx)
        if error:
            return error
        url = urljoin(config.api_base_url, "api/v1/accounting/company-categories/")
        payload = {
            "code": code,
            "name": name,
            "cashflowType": account_type,
            "isBookable": available_in_transactions,
            "description": description,
            "vatApplicability": vat_applicable,
            "suggestedVatRate": suggested_vat_rate,
        }
        return await _request(api, "POST", url, json_data=payload)

    @mcp.tool(title="Update Chart of Accounts Account", annotations=WRITE)
    async def update_chart_of_accounts_account(
        ctx: Context,
        account_id: str = Field(
            description="Account public ID from list_chart_of_accounts"
        ),
        name: Optional[str] = None,
        account_type: Optional[str] = Field(
            default=None, description="ASSET, LIABILITY, EQUITY, INCOME or EXPENSE"
        ),
        available_in_transactions: Optional[bool] = None,
        active: Optional[bool] = None,
        description: Optional[str] = None,
        vat_applicable: Optional[bool] = None,
        suggested_vat_rate: Optional[int] = Field(default=None, ge=0, le=100),
    ) -> Dict[str, Any]:
        """Edit a custom account, or hide/unhide a built-in account."""
        api, _company_id, error = _api_and_company(ctx)
        if error:
            return error
        url = urljoin(
            config.api_base_url, f"api/v1/accounting/company-categories/{account_id}/"
        )
        payload = _compact(
            {
                "name": name,
                "cashflowType": account_type,
                "isBookable": available_in_transactions,
                "isActive": active,
                "description": description,
                "vatApplicability": vat_applicable,
                "suggestedVatRate": suggested_vat_rate,
            }
        )
        return await _request(api, "PATCH", url, json_data=payload)

    @mcp.tool(title="Deactivate Chart of Accounts Account", annotations=DESTRUCTIVE)
    async def deactivate_chart_of_accounts_account(
        ctx: Context,
        account_id: str = Field(
            description="Account public ID from list_chart_of_accounts"
        ),
        confirmed: bool = Field(
            default=False,
            description="Must be true after the user confirms the account should be hidden",
        ),
    ) -> Dict[str, Any]:
        """Soft-delete an account. Existing postings remain in the immutable Ledger."""
        if not confirmed:
            return {
                "confirmationRequired": True,
                "warning": "This hides the account from future selection. Existing Ledger postings remain unchanged.",
            }
        api, _company_id, error = _api_and_company(ctx)
        if error:
            return error
        url = urljoin(
            config.api_base_url, f"api/v1/accounting/company-categories/{account_id}/"
        )
        return await _request(api, "DELETE", url)

    @mcp.tool(title="Switch Account Framework", annotations=DESTRUCTIVE)
    async def switch_account_framework(
        ctx: Context,
        framework_code: str = Field(
            description="Template code, for example skr03 or skr04"
        ),
        confirmed: bool = Field(
            default=False,
            description="Must be true only after the user explicitly accepts the remapping risk",
        ),
    ) -> Dict[str, Any]:
        """Switch SKR framework with the same explicit confirmation used by the Norman UI."""
        warning = (
            "Switching the account framework provisions a different system account master. "
            "Custom accounts are preserved, but existing transaction account assignments and "
            "reports may require review. The operation is not a casual navigation choice."
        )
        if not confirmed:
            return {"confirmationRequired": True, "warning": warning}
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        url = _company_url(company_id, "")
        return await _request(
            api,
            "PATCH",
            url,
            json_data={
                "chartOfAccounts": framework_code,
                "confirmChartOfAccountsSwitch": True,
            },
        )

    @mcp.tool(title="List Assets", annotations=READ_ONLY)
    async def list_assets(
        ctx: Context, page: int = Field(default=1, ge=1)
    ) -> Dict[str, Any]:
        """List fixed assets and their depreciation schedules."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(company_id, "accounting/assets/"),
            params={"page": page},
        )

    @mcp.tool(title="Get Asset", annotations=READ_ONLY)
    async def get_asset(ctx: Context, asset_id: str) -> Dict[str, Any]:
        """Get an asset including source transaction, useful life and annual depreciation."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api, "GET", _company_url(company_id, f"accounting/assets/{asset_id}/")
        )

    @mcp.tool(title="Create Asset", annotations=WRITE)
    async def create_asset(
        ctx: Context,
        name: str,
        asset_type: str = Field(description="tangible or intangible"),
        acquisition_date: str = Field(
            description="Original acquisition date in YYYY-MM-DD format"
        ),
        depreciation_basis: float = Field(
            gt=0, description="Net basis, or gross when input VAT is not deductible"
        ),
        useful_lifetime_months: int = Field(gt=0),
        gross_purchase_price: Optional[float] = None,
        business_use_percent: float = Field(default=100, ge=0, le=100),
        ledger_account_code: Optional[str] = None,
        transaction_id: Optional[str] = None,
        transaction_item_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an asset, optionally linked to a Norman Transaction or split item."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        payload = _compact(
            {
                "name": name,
                "type": asset_type,
                "status": "active",
                "date": acquisition_date,
                "depreciationDate": acquisition_date,
                "amount": depreciation_basis,
                "amountIncVat": gross_purchase_price,
                # The public form speaks in percentages; the Asset model stores a
                # fraction (1.00 == 100%). Keep that conversion at the MCP edge so
                # agents cannot accidentally create a 100x depreciation basis.
                "useProfessionalPart": business_use_percent / 100,
                "usefulLifetime": useful_lifetime_months,
                "amortizationMethod": "straightLine",
                "ledgerAccountCode": ledger_account_code,
                "transaction": transaction_id,
                "transactionItem": transaction_item_id,
            }
        )
        return await _request(
            api,
            "POST",
            _company_url(company_id, "accounting/assets/"),
            json_data=payload,
        )

    @mcp.tool(title="Update Asset", annotations=WRITE)
    async def update_asset(
        ctx: Context,
        asset_id: str,
        name: Optional[str] = None,
        acquisition_date: Optional[str] = None,
        depreciation_basis: Optional[float] = Field(default=None, gt=0),
        gross_purchase_price: Optional[float] = None,
        useful_lifetime_months: Optional[int] = Field(default=None, gt=0),
        business_use_percent: Optional[float] = Field(default=None, ge=0, le=100),
        ledger_account_code: Optional[str] = None,
        status: Optional[str] = Field(default=None, description="active, lost or sold"),
    ) -> Dict[str, Any]:
        """Edit an asset through the audited Asset service."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        payload = _compact(
            {
                "name": name,
                "date": acquisition_date,
                "depreciationDate": acquisition_date,
                "amount": depreciation_basis,
                "amountIncVat": gross_purchase_price,
                "usefulLifetime": useful_lifetime_months,
                "useProfessionalPart": business_use_percent / 100
                if business_use_percent is not None
                else None,
                "ledgerAccountCode": ledger_account_code,
                "status": status,
            }
        )
        return await _request(
            api,
            "PATCH",
            _company_url(company_id, f"accounting/assets/{asset_id}/"),
            json_data=payload,
        )

    @mcp.tool(title="Delete Asset", annotations=DESTRUCTIVE)
    async def delete_asset(
        ctx: Context, asset_id: str, confirmed: bool = False
    ) -> Dict[str, Any]:
        """Delete an asset only after explicit confirmation; audit/reversal rules remain server-side."""
        if not confirmed:
            return {
                "confirmationRequired": True,
                "warning": "Deleting an asset affects its depreciation schedule. Confirm after reviewing the asset.",
            }
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api, "DELETE", _company_url(company_id, f"accounting/assets/{asset_id}/")
        )

    @mcp.tool(title="List Ledger Journal", annotations=READ_ONLY)
    async def list_ledger_journal(
        ctx: Context,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        account: Optional[str] = None,
        source: Optional[str] = None,
        tax_treatment: Optional[str] = None,
        search: Optional[str] = None,
        ordering: str = Field(
            default="date_desc", description="Defaults to newest first"
        ),
        page: int = Field(default=1, ge=1),
    ) -> Dict[str, Any]:
        """Read the chronological double-entry audit trail with source and tax-treatment filters."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        params = _compact(
            {
                "dateFrom": date_from,
                "dateTo": date_to,
                "account": account,
                "source": source,
                "taxTreatment": tax_treatment,
                "search": search,
                "ordering": ordering,
                "page": page,
            }
        )
        return await _request(
            api,
            "GET",
            _company_url(company_id, "accounting/ledger/journal/"),
            params=params,
        )

    @mcp.tool(title="List Ledger Account Balances", annotations=READ_ONLY)
    async def list_ledger_account_balances(
        ctx: Context,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the SuSa: debit, credit and saldo for every used account."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(company_id, "accounting/ledger/accounts/"),
            params=_compact({"dateFrom": date_from, "dateTo": date_to}),
        )

    @mcp.tool(title="Get Ledger Account", annotations=READ_ONLY)
    async def get_ledger_account(
        ctx: Context,
        account_code: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a Kontenblatt with postings and a running balance for one account."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(company_id, f"accounting/ledger/accounts/{account_code}/"),
            params=_compact({"dateFrom": date_from, "dateTo": date_to}),
        )

    @mcp.tool(title="List Ledger Open Items", annotations=READ_ONLY)
    async def list_ledger_open_items(
        ctx: Context,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the derived debtor/creditor open-item list and ageing."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(company_id, "accounting/ledger/open-items/"),
            params=_compact({"dateFrom": date_from, "dateTo": date_to}),
        )

    @mcp.tool(title="Get Cash Book", annotations=READ_ONLY)
    async def get_cash_book(
        ctx: Context,
        year: int = Field(ge=2000, le=2100),
        month: Optional[int] = Field(default=None, ge=1, le=12),
    ) -> Dict[str, Any]:
        """Read the cash register derived from CASH transactions and the Kasse account."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(company_id, "accounting/cash-book/"),
            params=_compact({"year": year, "month": month}),
        )

    async def _statement(
        ctx: Context,
        endpoint: str,
        date_from: str,
        date_to: str,
        period_type: str,
        previous_date_from: Optional[str],
        previous_date_to: Optional[str],
    ) -> Dict[str, Any]:
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(company_id, endpoint),
            params=_compact(
                {
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "periodType": period_type,
                    "previousDateFrom": previous_date_from,
                    "previousDateTo": previous_date_to,
                }
            ),
        )

    @mcp.tool(title="Get Ledger Profit and Loss", annotations=READ_ONLY)
    async def get_ledger_profit_and_loss(
        ctx: Context,
        date_from: str,
        date_to: str,
        period_type: str = Field(default="year", description="month, quarter or year"),
        previous_date_from: Optional[str] = None,
        previous_date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get GuV/P&L calculated exclusively from materialized Ledger postings."""
        return await _statement(
            ctx,
            "accounting/ledger/profit-loss/",
            date_from,
            date_to,
            period_type,
            previous_date_from,
            previous_date_to,
        )

    @mcp.tool(title="Get Ledger Balance Sheet", annotations=READ_ONLY)
    async def get_ledger_balance_sheet(
        ctx: Context,
        date_from: str,
        date_to: str,
        period_type: str = Field(default="year", description="month, quarter or year"),
        previous_date_from: Optional[str] = None,
        previous_date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get the balance sheet using the same mappings as Annual Close and E-Bilanz."""
        return await _statement(
            ctx,
            "accounting/ledger/balance-sheet/",
            date_from,
            date_to,
            period_type,
            previous_date_from,
            previous_date_to,
        )

    @mcp.tool(title="Create Manual Ledger Entry", annotations=WRITE)
    async def create_manual_ledger_entry(
        ctx: Context,
        booking_date: str,
        debit_code: str,
        credit_code: str,
        amount: float = Field(gt=0),
        memo: str = "",
        tax_treatment: str = "NONE",
        tax_country_scope: str = "UNKNOWN",
        tax_rate: Optional[float] = Field(default=None, ge=0, le=100),
        input_tax_deduction_percent: Optional[float] = Field(
            default=None, ge=0, le=100
        ),
    ) -> Dict[str, Any]:
        """Create a balanced manual posting with explicit tax semantics."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        payload = _compact(
            {
                "bookingDate": booking_date,
                "debitCode": debit_code,
                "creditCode": credit_code,
                "amount": amount,
                "memo": memo,
                "taxTreatment": tax_treatment,
                "taxCountryScope": tax_country_scope,
                "taxRate": tax_rate,
                "inputTaxDeductionPercent": input_tax_deduction_percent,
            }
        )
        return await _request(
            api,
            "POST",
            _company_url(company_id, "accounting/ledger/manual-entries/"),
            json_data=payload,
        )

    @mcp.tool(title="Get Manual Ledger Entry", annotations=READ_ONLY)
    async def get_manual_ledger_entry(ctx: Context, entry_id: str) -> Dict[str, Any]:
        """Get a manual posting and its immutable reversal links."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(company_id, f"accounting/ledger/manual-entries/{entry_id}/"),
        )

    @mcp.tool(title="Reverse Manual Ledger Entry", annotations=DESTRUCTIVE)
    async def reverse_manual_ledger_entry(
        ctx: Context,
        entry_id: str,
        confirmed: bool = Field(
            default=False,
            description="Must be true after reviewing the original posting",
        ),
        booking_date: Optional[str] = None,
        memo: str = "",
    ) -> Dict[str, Any]:
        """Correct a manual posting by Storno; the original entry is never deleted or edited."""
        if not confirmed:
            return {
                "confirmationRequired": True,
                "warning": "This creates an immutable Storno with debit and credit reversed.",
            }
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "POST",
            _company_url(
                company_id, f"accounting/ledger/manual-entries/{entry_id}/reverse/"
            ),
            json_data=_compact({"bookingDate": booking_date, "memo": memo}),
        )

    @mcp.tool(title="List Annual Closes", annotations=READ_ONLY)
    async def list_annual_closes(ctx: Context) -> Dict[str, Any]:
        """List fiscal-year close workspaces and their current status."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api, "GET", _company_url(company_id, "accounting/annual-closes/")
        )

    @mcp.tool(title="Create Annual Close", annotations=WRITE)
    async def create_annual_close(
        ctx: Context,
        fiscal_year_begin: str = Field(
            description="Fiscal-year start in YYYY-MM-DD format"
        ),
        fiscal_year_end: str = Field(
            description="Fiscal-year end in YYYY-MM-DD format"
        ),
    ) -> Dict[str, Any]:
        """Create a Draft annual-close workspace; this does not lock or submit the year."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "POST",
            _company_url(company_id, "accounting/annual-closes/"),
            json_data={
                "fiscalYearBegin": fiscal_year_begin,
                "fiscalYearEnd": fiscal_year_end,
            },
        )

    @mcp.tool(title="Get Annual Close", annotations=READ_ONLY)
    async def get_annual_close(ctx: Context, annual_close_id: str) -> Dict[str, Any]:
        """Get one annual-close workspace and its Draft/locked/submitted status."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(company_id, f"accounting/annual-closes/{annual_close_id}/"),
        )

    @mcp.tool(title="Create Annual Close Entry", annotations=WRITE)
    async def create_annual_close_entry(
        ctx: Context,
        annual_close_id: str,
        debit_code: str,
        credit_code: str,
        amount: float = Field(gt=0),
        memo: str = "",
        booking_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Post a closing adjustment to a Draft annual close; locked years remain server-protected."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "POST",
            _company_url(
                company_id, f"accounting/annual-closes/{annual_close_id}/entries/"
            ),
            json_data=_compact(
                {
                    "debitCode": debit_code,
                    "creditCode": credit_code,
                    "amount": amount,
                    "memo": memo,
                    "bookingDate": booking_date,
                    "source": "CLOSING",
                }
            ),
        )

    @mcp.tool(title="Get Annual Close Workbook", annotations=READ_ONLY)
    async def get_annual_close_workbook(
        ctx: Context, annual_close_id: str
    ) -> Dict[str, Any]:
        """Review SuSa, Bilanz, GuV, BVV and blocking validations. This never locks or submits."""
        api, company_id, error = _api_and_company(ctx)
        if error:
            return error
        return await _request(
            api,
            "GET",
            _company_url(
                company_id, f"accounting/annual-closes/{annual_close_id}/workbook/"
            ),
        )
