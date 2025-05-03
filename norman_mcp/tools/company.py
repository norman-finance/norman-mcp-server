import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from datetime import datetime

from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

def register_company_tools(mcp):
    """Register all company-related tools with the MCP server."""
    
    @mcp.tool()
    async def get_company_details(ctx: Context) -> Dict[str, Any]:
        """Get detailed information about the user's company."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        return api._make_request("GET", company_url)

    @mcp.tool()
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

    @mcp.tool()
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
    ) -> Dict[str, Any]:
        """Update company information."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        
        # Get current company data
        current_data = api._make_request("GET", company_url)
        
        # Update only provided fields
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

        # If no fields provided, return current data
        if not update_data:
            return {"message": "No fields provided for update.", "company": current_data}
        
        # Update company data
        updated_company = api._make_request("PATCH", company_url, json_data=update_data)
        return {"message": "Company updated successfully", "company": updated_company} 