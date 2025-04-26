import logging
import requests
from typing import Dict, Any, Optional
from urllib.parse import urljoin

from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

def register_client_tools(mcp):
    """Register all client-related tools with the MCP server."""
    
    @mcp.tool()
    async def list_clients(
        ctx: Context
    ) -> Dict[str, Any]:
        """Get a list of all clients."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        clients_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/clients/"
        )
        
        return api._make_request("GET", clients_url)

    @mcp.tool()
    async def get_client(
        ctx: Context,
        client_id: str
    ) -> Dict[str, Any]:
        """Get detailed information about a specific client."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        client_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/clients/{client_id}/"
        )
        
        return api._make_request("GET", client_url)

    @mcp.tool()
    async def create_client(
        ctx: Context,
        name: str,
        client_type: str = "business",
        address: Optional[str] = None,
        zip_code: Optional[str] = None,
        email: Optional[str] = None,
        country: Optional[str] = None,
        vat_number: Optional[str] = None,
        city: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new client."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        if client_type not in ["business", "private"]:
            return {"error": "client_type must be either 'business' or 'private'"}
        
        clients_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/clients/"
        )
        
        client_data = {
            "name": name,
            "clientType": client_type,
            "company": company_id
        }
        
        # Add optional fields if provided
        if address:
            client_data["address"] = address
        if zip_code:
            client_data["zipCode"] = zip_code
        if email:
            client_data["email"] = email
        if country:
            client_data["country"] = country
        if vat_number:
            client_data["vatNumber"] = vat_number
        if city:
            client_data["city"] = city
        if phone:
            client_data["phoneNumber"] = phone
        
        return api._make_request("POST", clients_url, json_data=client_data)

    @mcp.tool()
    async def update_client(
        ctx: Context,
        client_id: str,
        name: Optional[str] = None,
        client_type: Optional[str] = None,
        address: Optional[str] = None,
        zip_code: Optional[str] = None,
        email: Optional[str] = None,
        country: Optional[str] = None,
        vat_number: Optional[str] = None,
        city: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update an existing client."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        if client_type and client_type not in ["business", "private"]:
            return {"error": "client_type must be either 'business' or 'private'"}
        
        client_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/clients/{client_id}/"
        )
        
        # Get current client data
        current_data = api._make_request("GET", client_url)
        
        # Update only provided fields
        update_data = {}
        if name:
            update_data["name"] = name
        if client_type:
            update_data["clientType"] = client_type
        if address:
            update_data["address"] = address
        if zip_code:
            update_data["zipCode"] = zip_code
        if email:
            update_data["email"] = email
        if country:
            update_data["country"] = country
        if vat_number:
            update_data["vatNumber"] = vat_number
        if city:
            update_data["city"] = city
        if phone:
            update_data["phoneNumber"] = phone
        
        # If no fields provided, return current data
        if not update_data:
            return {"message": "No fields provided for update.", "client": current_data}
        
        return api._make_request("PATCH", client_url, json_data=update_data)

    @mcp.tool()
    async def delete_client(
        ctx: Context,
        client_id: str
    ) -> Dict[str, Any]:
        """Delete a client."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        client_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/clients/{client_id}/"
        )
        
        api._make_request("DELETE", client_url)
        return {"message": "Client deleted successfully"} 