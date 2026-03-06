import logging
from typing import Any, Dict, Optional
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
            openWorldHint=True,
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
