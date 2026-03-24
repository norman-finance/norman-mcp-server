import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from datetime import datetime
from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

def register_company_tools(mcp):
    """Register all company-related tools with the MCP server."""
    
    @mcp.tool(
        title="Get Company Details",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_company_details(ctx: Context) -> Dict[str, Any]:
        """Get detailed information about the user's company."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        return api._make_request("GET", company_url)

    @mcp.tool(
        title="Get Company Balance",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_company_balance(ctx: Context) -> Dict[str, Any]:
        """
        Get the current balance of the company.
        
        Returns:
            Company balance information
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        balance_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/balance/"
        )
        
        return api._make_request("GET", balance_url)

    @mcp.tool(
        title="Update Company Details",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def update_company_details(
        ctx: Context,
        name: Optional[str] = None,
        profession: Optional[str] = None,
        address: Optional[str] = None,
        zip_code: Optional[str] = None,
        city: Optional[str] = None,
        country: Optional[str] = None,
        vat_id: Optional[str] = None,
        tax_id: Optional[str] = None,
        phone: Optional[str] = None,
        tax_state: Optional[str] = None,
        activity_start: Optional[datetime] = None,
        chart_of_accounts: Optional[str] = Field(default=None, description="Chart of accounts template code: 'skr03' or 'skr04'. Only for SME companies."),
        datev_advisor_number: Optional[str] = Field(default=None, description="DATEV tax advisor number"),
        datev_client_number: Optional[str] = Field(default=None, description="DATEV client/Mandant number"),
    ) -> Dict[str, Any]:
        """Update company information. For SME companies you can also set chart_of_accounts, DATEV advisor/client numbers."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        
        update_data = {}
        
        if name:
            update_data["name"] = name
        if profession:
            update_data["profession"] = profession
        if address:
            update_data["address"] = address
        if zip_code:
            update_data["zipCode"] = zip_code
        if city:
            update_data["city"] = city
        if country:
            update_data["country"] = country
        if vat_id:
            update_data["vatNumber"] = vat_id
        if tax_id:
            update_data["taxNumber"] = tax_id
        if phone:
            update_data["phoneNumber"] = phone
        if tax_state:
            update_data["taxState"] = tax_state
        if activity_start:
            update_data["activityStart"] = activity_start
        if chart_of_accounts:
            update_data["chartOfAccounts"] = chart_of_accounts
        if datev_advisor_number is not None:
            update_data["datevAdvisorNumber"] = datev_advisor_number
        if datev_client_number is not None:
            update_data["datevClientNumber"] = datev_client_number

        if not update_data:
            current_data = api._make_request("GET", company_url)
            return {"message": "No fields provided for update.", "company": current_data}
        
        updated_company = api._make_request("PATCH", company_url, json_data=update_data)
        return {"message": "Company updated successfully", "company": updated_company}

    @mcp.tool(
        title="List Company Categories",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_company_categories(
        ctx: Context,
        cashflow_type: Optional[str] = Field(default=None, description="Filter by cashflow type: INCOME or EXPENSE"),
    ) -> Dict[str, Any]:
        """
        List SME company categories from the DATEV chart of accounts (SKR03/SKR04).
        These categories are specific to the company and are used for GmbH/UG bookkeeping.
        Each category has a code (e.g. '4200'), name, and cashflow type.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        categories_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/"
        )
        
        params = {"pageSize": 200}
        if cashflow_type:
            params["cashflowType"] = cashflow_type
        
        return api._make_request("GET", categories_url, params=params)

    @mcp.tool(
        title="List Chart of Accounts Templates",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_coa_templates(ctx: Context) -> Dict[str, Any]:
        """List available Chart of Accounts templates (e.g. SKR03, SKR04) that can be assigned to an SME company."""
        api = ctx.request_context.lifespan_context["api"]
        
        templates_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/templates/"
        )
        
        return api._make_request("GET", templates_url)

    @mcp.tool(
        title="Trigger DATEV Export",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def trigger_datev_export(
        ctx: Context,
        date_from: str = Field(description="Start date for export in YYYY-MM-DD format"),
        date_to: str = Field(description="End date for export in YYYY-MM-DD format"),
        include_documents: bool = Field(default=True, description="Whether to include attached documents in the ZIP"),
    ) -> Dict[str, Any]:
        """
        Trigger a DATEV export for the company's transactions in the specified period.
        Generates a ZIP containing a DATEV EXTF CSV, a human-readable statement CSV,
        and optionally all attached documents. Only finalized transactions are included.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        export_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/datev-export/"
        )
        
        export_data = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "includeDocuments": include_documents,
        }
        
        return api._make_request("POST", export_url, json_data=export_data)