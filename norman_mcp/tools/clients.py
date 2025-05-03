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
        """
        Get a list of all clients for the company.
        
        Returns:
            List of clients with their details
        """
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
        """
        Get detailed information about a specific client.
        
        Args:
            client_id: ID of the client to retrieve
            
        Returns:
            Detailed client information
        """
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
        """
        Create a new client.
        
        Args:
            name: Client name or business name
            client_type: Type of client (defaults to "business"), Options: "business", "private"
            address: Client physical address
            zip_code: Client postal/zip code
            email: Client email address
            country: Client country code (e.g. "DE")
            vat_number: Client VAT number
            city: Client city
            phone: Client phone number
            
        Returns:
            Newly created client record
        """
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
            "clientType": client_type
        }
    
        if email:
            client_data["email"] = email
        if phone:
            client_data["phone"] = phone
        if vat_number:
            client_data["vatNumber"] = vat_number
        if address:
            client_data["address"] = address
        if zip_code:
            client_data["zipCode"] = zip_code
        if country:
            client_data["country"] = country
        if city:
            client_data["city"] = city
            
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
        """
        Update an existing client.
        
        Args:
            client_id: ID of the client to update
            name: Updated client name
            client_type: Updated client type ("business" or "private")
            address: Updated client physical address
            zip_code: Updated client postal/zip code
            email: Updated client email address
            country: Updated client country code (e.g. "DE")
            vat_number: Updated client VAT number
            city: Updated client city
            phone: Updated client phone number
            
        Returns:
            Updated client record
        """
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
        if email:
            update_data["email"] = email
        if phone:
            update_data["phone"] = phone
        if vat_number:
            update_data["vatNumber"] = vat_number
        if address:
            update_data["address"] = address
        if zip_code:
            update_data["zipCode"] = zip_code
        if country:
            update_data["country"] = country
        if city:
            update_data["city"] = city
        
        # If no fields provided, return current data
        if not update_data:
            return {"message": "No fields provided for update.", "client": current_data}
        
        return api._make_request("PATCH", client_url, json_data=update_data)

    @mcp.tool()
    async def delete_client(
        ctx: Context,
        client_id: str
    ) -> Dict[str, Any]:
        """
        Delete a client.
        
        Args:
            client_id: ID of the client to delete
            
        Returns:
            Confirmation of deletion
        """
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