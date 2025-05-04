from typing import Dict, Any, List
from urllib.parse import urljoin
from norman_mcp import config

def register_resources(mcp):
    """Register all resource endpoints with the MCP server."""
    
    @mcp.resource("company://current")
    async def get_company() -> str:
        """Get details about a company by ID."""
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]

        # Now get the company details with our company ID
        company_id = api.company_id
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        
        try:
            # Use a direct request with our token to avoid any issues
            import requests
            headers = {
                "Authorization": f"Bearer {api.access_token}",
                "User-Agent": "NormanMCPServer/0.1.0",
                "X-Requested-With": "XMLHttpRequest",
            }
            
            response = requests.get(
                company_url,
                headers=headers,
                timeout=config.NORMAN_API_TIMEOUT
            )
            
            response.raise_for_status()
            company_data = response.json()
            
            # Format the company information for display
            company_info = (
                f"# {company_data.get('name', 'Unknown Company')}\n\n"
                f"**Account Type**: {company_data.get('accountType', 'N/A')}\n"
                f"**Activity Start**: {company_data.get('activityStart', 'N/A')}\n"
                f"**VAT ID**: {company_data.get('vatNumber', 'N/A')}\n"
                f"**Tax ID**: {company_data.get('taxNumber', 'N/A')}\n"
                f"**Tax State**: {company_data.get('taxState', 'N/A')}\n"
                f"**Profession**: {company_data.get('profession', 'N/A')}\n"
                f"**Address**: {company_data.get('address', '')} "
                f"{company_data.get('zipCode', '')} "
                f"{company_data.get('city', '')}, "
                f"{company_data.get('countryName', '')}\n"
            )
            
            return company_info
        except Exception as e:
            return f"Error getting company details: {str(e)}"

    @mcp.resource("transactions://list/{page}/{page_size}")
    async def list_transactions(page: int = 1, page_size: int = 100) -> str:
        """List transactions with pagination."""
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return "No company available. Please authenticate first."
        
        transactions_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/accounting/transactions/"
        )
        
        params = {
            "page": page,
            "pageSize": page_size
        }
        
        return api._make_request("GET", transactions_url, params=params)

    @mcp.resource("invoices://list/{page}/{page_size}")
    async def list_invoices(page: int = 1, page_size: int = 100) -> str:
        """List invoices with pagination."""
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return "No company available. Please authenticate first."
        
        invoices_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/invoices/"
        )
        
        params = {
            "page": page,
            "pageSize": page_size
        }
        
        return api._make_request("GET", invoices_url, params=params)

    @mcp.resource("clients://list/{page}/{page_size}")
    async def list_clients(page: int = 1, page_size: int = 100) -> List[Dict[str, Any]]:
        """
        List clients with optional filtering.
        
        Args:
            name: Filter clients by name (partial match)
            email: Filter clients by email (partial match)
            limit: Maximum number of clients to return, default is 100
            
        Returns:
            List of client records matching the criteria
        """
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        clients_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/clients/"
        )
        
        params = {
            "page": page,
            "pageSize": page_size
        }
        
        return api._make_request("GET", clients_url, params=params)

    @mcp.resource("taxes://list/{page}/{page_size}")
    async def list_taxes(page: int = 1, page_size: int = 100) -> str:
        """List tax reports available for the user's company."""
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return "No company available. Please authenticate first."
        
        taxes_url = urljoin(config.api_base_url, "api/v1/taxes/reports/")
        
        params = {
            "page": page,
            "pageSize": page_size
        }
        
        return api._make_request("GET", taxes_url, params=params)

    @mcp.resource("categories://list")
    async def list_categories() -> str:
        """List transaction categories."""
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        # Default pagination parameters
        page = 1
        page_size = 10
        
        if not company_id:
            return "No company available. Please authenticate first."
        
        categories_url = urljoin(
            config.api_base_url, 
            f"api/v1/accounting/categories/"
        )
        
        params = {
            "page": page,
            "pageSize": page_size
        }
        
        categories_data = api._make_request("GET", categories_url, params=params)
        return categories_data.get("results", []) 