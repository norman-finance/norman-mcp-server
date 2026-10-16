from norman_mcp.bookkeeping_context import company_bookkeeping_context
from norman_mcp.context import Context, get_api_client
from typing import Dict, Any, List
from urllib.parse import urljoin
from norman_mcp import config
from norman_mcp.tools.taxes import reports_url
from norman_mcp.company_profile import without_company_personal_identifiers

def register_resources(mcp):
    """Register all resource endpoints with the MCP server."""
    
    @mcp.resource("company://current")
    async def get_company() -> str:
        """Get the selected company country, accounting currency, legal form and chart of accounts."""
        api = get_api_client()

        company_id = api.company_id
        if not company_id:
            return "No company selected."
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        
        try:
            # The API client resolves the caller's token per request; the
            # static token is empty in hosted OAuth mode ("Bearer None", 401).
            company_data = without_company_personal_identifiers(api._make_request("GET", company_url))
            if not isinstance(company_data, dict) or company_data.get("error"):
                return f"Error getting company details: {company_data}"

            return company_bookkeeping_context(company_data)
        except Exception as e:
            return f"Error getting company details: {str(e)}"

    @mcp.resource("transactions://list/{page}/{page_size}")
    async def list_transactions(ctx: Context, page: int = 1, page_size: int = 100) -> str:
        """List transactions with pagination."""
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
    async def list_invoices(ctx: Context, page: int = 1, page_size: int = 100) -> str:
        """List invoices with pagination."""
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
    async def list_clients(ctx: Context, page: int = 1, page_size: int = 100) -> List[Dict[str, Any]]:
        """
        List clients with optional filtering.
        
        Args:
            name: Filter clients by name (partial match)
            email: Filter clients by email (partial match)
            limit: Maximum number of clients to return, default is 100
            
        Returns:
            List of client records matching the criteria
        """
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
    async def list_taxes(ctx: Context, page: int = 1, page_size: int = 100) -> str:
        """List tax reports available for the user's company."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return "No company available. Please authenticate first."
        
        # Company-scoped: the unscoped route ignores X-Company-Id (see tools.taxes.reports_url).
        taxes_url = reports_url(company_id)
        
        params = {
            "page": page,
            "pageSize": page_size
        }
        
        return api._make_request("GET", taxes_url, params=params)

    @mcp.resource("categories://list")
    async def list_categories() -> str:
        """List freelance transaction categories (used for non-SME companies)."""
        api = get_api_client()
        company_id = api.company_id
        
        if not company_id:
            return "No company available. Please authenticate first."
        
        categories_url = urljoin(
            config.api_base_url, 
            "api/v1/accounting/categories/"
        )
        
        params = {"page": 1, "pageSize": 200}
        
        categories_data = api._make_request("GET", categories_url, params=params)
        return categories_data.get("results", [])

    @mcp.resource("tax-advisor-clients://list")
    async def list_tax_advisor_client_companies() -> str:
        """List all companies managed by the authenticated tax advisor.
        
        Returns each client company's ID, name, account type, transaction count,
        and number of transactions missing receipts. Use the company IDs with the
        switch_company tool to change the active company context.
        """
        api = get_api_client()

        clients_url = urljoin(config.api_base_url, "api/v1/tax-advisor/clients/")

        # Per-request client, as for company:// above.
        clients = api._make_request("GET", clients_url)
        if isinstance(clients, dict) and clients.get("error"):
            return f"Error fetching tax advisor clients: {clients}"

        client_list = clients if isinstance(clients, list) else clients.get("results", [])

        if not client_list:
            return "No client companies found. You may not be registered as a tax advisor or have no active clients."

        lines = [
            f"# Your Client Companies ({len(client_list)})\n",
            f"**Active company**: {api.company_id or 'None selected'}\n",
        ]
        for c in client_list:
            active = " ← active" if c.get("public_id") == api.company_id else ""
            lines.append(
                f"- **{c.get('name', 'Unknown')}** (`{c.get('public_id')}`){active}\n"
                f"  Account type: {c.get('account_type', 'N/A')} · "
                f"Transactions: {c.get('transaction_count', 0)} · "
                f"Missing docs: {c.get('missing_docs_count', 0)}"
            )

        lines.append(f"\nUse `switch_company` tool with a company ID to change the active company.")
        return "\n".join(lines)

    @mcp.resource("skr-catalog://search/{query}")
    async def search_skr_catalog(ctx: Context, query: str) -> str:
        """Search the full SKR chart of accounts (SKR03/SKR04) by code or name.
        
        SME only — this resource is for GmbH/UG companies that use a DATEV
        chart of accounts. Returns nothing useful for freelance accounts.
        
        Exposes the complete catalog of ~1000+ account entries, not just the
        categories provisioned for the company.
        
        Args:
            query: Account code prefix (e.g. '42', '6') or name keyword (e.g. 'rent')
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return "No company available. Please authenticate first."

        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        company = api._make_request("GET", company_url)
        if company.get("country") != "DE" or not company.get("isSme"):
            return (
                "SKR catalog search requires a German SME (GmbH/UG). "
                "Use company-categories://list for the selected company chart."
            )

        lookup_url = urljoin(
            config.api_base_url,
            "api/v1/accounting/company-categories/skr-lookup/",
        )

        results = api._make_request("GET", lookup_url, params={"q": query})

        if isinstance(results, dict) and "error" in results:
            return f"Error searching SKR catalog: {results['error']}"

        if not results:
            return f"No entries found for query '{query}'."

        lines = [f"# SKR Catalog Search: \"{query}\" ({len(results)} results)\n"]
        for entry in results:
            lines.append(
                f"- **{entry['accountNumber']}** — {entry['nameDe']} / {entry['nameEn']}"
            )
        return "\n".join(lines)

    @mcp.resource("company-categories://list")
    async def list_company_categories() -> str:
        """List company-specific bookkeeping categories (company chart: SKR03/SKR04, PL_KPIR or PL_FULL).
        
        Use these for any company with usesCompanyChart=true, including Polish JDG
        and sp. z o.o. Each category has an account code, name,
        cashflow type, and optional metadata for amortization rules.
        """
        api = get_api_client()
        company_id = api.company_id
        
        if not company_id:
            return "No company available. Please authenticate first."
        
        categories_url = urljoin(
            config.api_base_url, 
            "api/v1/accounting/company-categories/"
        )
        
        params = {"pageSize": 200}
        
        categories_data = api._make_request("GET", categories_url, params=params)
        return categories_data.get("results", [])
