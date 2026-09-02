import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from pydantic import Field

from norman_mcp import config
from norman_mcp.context import Context

logger = logging.getLogger(__name__)

_SME_ONLY_ERROR = {
    "error": (
        "This tool is only available for SME companies (GmbH/UG) that use a DATEV "
        "chart of accounts (SKR03/SKR04). The current company is a freelance account. "
        "Use the 'categorize_transaction' tool instead for freelance category detection."
    ),
}


async def _check_sme(api) -> bool:
    """Return True if the active company is an SME account with a chart of accounts."""
    company_url = urljoin(config.api_base_url, f"api/v1/companies/{api.company_id}/")
    company = api._make_request("GET", company_url)
    return bool(company.get("isSme"))


def register_category_tools(mcp):
    """Register SME-only tools for searching the full SKR chart of accounts catalog.

    IMPORTANT: These tools are for SME (GmbH/UG) companies ONLY.
    They search the full SKR03/SKR04 DATEV standard chart of accounts.
    For freelance accounts, use 'categorize_transaction' instead — it uses a
    different set of freelance categories and a separate AI flow.
    """

    @mcp.tool(
        title="Search SKR Categories by Code (SME only)",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def search_skr_by_code(
        ctx: Context,
        code: str = Field(description="Account number or prefix to search for, e.g. '47', '4200', '6'"),
    ) -> Dict[str, Any]:
        """
        Search the FULL SKR chart of accounts (SKR03 or SKR04) by account code.

        ⚠️ SME ONLY — this tool works exclusively for GmbH/UG companies with a
        DATEV chart of accounts. For freelance accounts use 'categorize_transaction'.

        Searches the complete catalog (~1000+ entries), NOT just the company's
        provisioned categories. Use when you know the account number or its prefix.

        Returns matching entries with accountNumber, nameDe, nameEn.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        if not await _check_sme(api):
            return _SME_ONLY_ERROR

        lookup_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/skr-lookup/",
        )
        return api._make_request("GET", lookup_url, params={"q": code})

    @mcp.tool(
        title="AI Category Suggestion (SME only)",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def suggest_skr_category(
        ctx: Context,
        query: str = Field(
            description=(
                "Natural-language description of the category you're looking for, "
                "e.g. 'office rent', 'Büromöbel', 'software subscriptions', "
                "'Reisekosten Arbeitnehmer'"
            ),
        ),
    ) -> Dict[str, Any]:
        """
        Use AI to find the best matching SKR categories by name or description.

        ⚠️ SME ONLY — this tool works exclusively for GmbH/UG companies with a
        DATEV chart of accounts (SKR03/SKR04). For freelance accounts use
        'categorize_transaction' which has its own AI-powered category detection.

        Sends the query to OpenAI along with the full SKR catalog as context,
        so it can semantically match even vague or partial descriptions.
        Returns up to 5 best matching entries with accountNumber, nameDe, nameEn.

        NOTE: This calls OpenAI — prefer search_skr_by_code when you have a code.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        if not await _check_sme(api):
            return _SME_ONLY_ERROR

        suggest_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/skr-ai-suggest/",
        )
        result = api._make_request("GET", suggest_url, params={"q": query})

        if isinstance(result, list) and len(result) == 0:
            return {
                "message": (
                    "No matching categories found. Try a different description "
                    "or use search_skr_by_code with an account number."
                ),
                "results": [],
            }
        return result

    @mcp.tool(
        title="Create Company Category (SME only)",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_company_category(
        ctx: Context,
        code: str = Field(description="Account number code, e.g. '4200'"),
        name: str = Field(description="Category name in English"),
        cashflow_type: str = Field(description="INCOME or EXPENSE"),
        name_de: Optional[str] = Field(default=None, description="Category name in German (optional)"),
        description: Optional[str] = Field(default=None, description="Optional description"),
    ) -> Dict[str, Any]:
        """
        Create a new custom company category for the active SME company.

        ⚠️ SME ONLY — only works for GmbH/UG companies with a DATEV chart of
        accounts. Not applicable to freelance accounts.

        Use search_skr_by_code or suggest_skr_category first to find the right
        account number from the full SKR catalog, then create the category here.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        if not await _check_sme(api):
            return _SME_ONLY_ERROR

        categories_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/",
        )

        body: Dict[str, Any] = {
            "code": code,
            "name": name,
            "cashflowType": cashflow_type,
        }
        if name_de:
            body["nameDe"] = name_de
        if description:
            body["description"] = description

        return api._make_request("POST", categories_url, json_data=body)

    @mcp.tool(
        title="Hide or Unhide Company Categories (SME only)",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def set_company_categories_visibility(
        ctx: Context,
        action: str = Field(description="'hide' to take the categories out of use, 'unhide' to bring them back"),
        chart_template: Optional[str] = Field(
            default=None,
            description=(
                "Select every row provisioned from this chart of accounts: 'skr03', 'skr04', "
                "'PL_FULL', 'PL_KPIR'. This is how you clean up a company that ended up with "
                "two charts at once — e.g. hide chart_template='skr04' to leave only SKR03."
            ),
        ),
        codes: Optional[List[str]] = Field(default=None, description="Select by account code, e.g. ['4200', '6815']"),
        category_ids: Optional[List[str]] = Field(
            default=None,
            description="Select explicit category ids as returned by list_company_categories",
        ),
        cashflow_type: Optional[str] = Field(default=None, description="Restrict to INCOME, EXPENSE or EQUITY rows"),
        include_custom: bool = Field(
            default=False,
            description=(
                "Also affect categories the company created itself. Off by default so a "
                "chart-wide sweep never touches hand-made accounts; ids always apply."
            ),
        ),
        dry_run: bool = Field(
            default=False,
            description="Return the selection without changing anything. Use before a chart-wide sweep.",
        ),
    ) -> Dict[str, Any]:
        """
        Hide or unhide SME company categories in bulk.

        ⚠️ SME ONLY — GmbH/UG companies with a DATEV chart of accounts.

        Hidden categories disappear from the category pickers in the app and from
        the candidate list the AI categorizer picks from. Nothing is deleted:
        transactions already booked on a hidden category keep it (the result
        reports transactionsCount / itemsCount per row), and unhiding restores
        the row exactly as it was.

        The main use: a company whose chart was provisioned twice and now shows
        both SKR03 and SKR04 accounts. Hide the chart it does not use.

        Selectors combine with AND and at least one is required. A non-zero
        summary.skippedCustom means the filter passed over hand-made accounts —
        rerun with include_custom=true if the user meant those too. Preview with
        dry_run=true and tell the user what would be hidden before doing it for
        real — this changes what they can book on.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        if not await _check_sme(api):
            return _SME_ONLY_ERROR

        normalized = (action or "").strip().lower()
        if normalized not in ("hide", "unhide"):
            return {"error": f"Unknown action '{action}'. Use 'hide' or 'unhide'."}

        body: Dict[str, Any] = {
            "isActive": normalized == "unhide",
            "includeCustom": include_custom,
            "dryRun": dry_run,
        }
        if chart_template:
            body["chartTemplate"] = chart_template
        if codes:
            body["codes"] = codes
        if category_ids:
            body["categoryIds"] = category_ids
        if cashflow_type:
            body["cashflowType"] = cashflow_type

        visibility_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/set-visibility/",
        )
        return api._make_request("POST", visibility_url, json_data=body)
