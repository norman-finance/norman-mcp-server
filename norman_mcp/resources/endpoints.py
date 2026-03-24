from typing import Dict, Any, List
from urllib.parse import urljoin
from norman_mcp import config

def register_resources(mcp):
    """Register all resource endpoints with the MCP server."""
    
    @mcp.resource("company://current")
    async def get_company() -> str:
        """Get details about the current company including SME status and Chart of Accounts."""
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]

        company_id = api.company_id
        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        
        try:
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

            is_sme = company_data.get('isSme', False)
            account_type = company_data.get('accountType', 'N/A')
            coa = company_data.get('chartOfAccounts')
            coa_info = f"{coa['name']} ({coa['code'].upper()})" if coa else "None"
            
            company_info = (
                f"# {company_data.get('name', 'Unknown Company')}\n\n"
                f"**Account Type**: {account_type}\n"
                f"**Is SME (GmbH/UG)**: {'Yes' if is_sme else 'No'}\n"
                f"**Chart of Accounts**: {coa_info}\n"
                f"**Activity Start**: {company_data.get('activityStart', 'N/A')}\n"
                f"**VAT ID**: {company_data.get('vatNumber', 'N/A')}\n"
                f"**Tax ID**: {company_data.get('taxNumber', 'N/A')}\n"
                f"**Tax State**: {company_data.get('taxState', 'N/A')}\n"
                f"**Profession**: {company_data.get('profession', 'N/A')}\n"
                f"**DATEV Advisor Number**: {company_data.get('datevAdvisorNumber', 'N/A')}\n"
                f"**DATEV Client Number**: {company_data.get('datevClientNumber', 'N/A')}\n"
                f"**Address**: {company_data.get('address', '')} "
                f"{company_data.get('zipCode', '')} "
                f"{company_data.get('city', '')}, "
                f"{company_data.get('countryName', '')}\n"
            )

            if is_sme:
                company_info += (
                    f"\n## SME Bookkeeping Info\n"
                    f"This company uses **accrual-based accounting** (Soll-Versteuerung).\n"
                    f"Tax obligations are based on the document/invoice date, not the payment date.\n"
                    f"Categories come from the DATEV standard chart of accounts ({coa_info}).\n"
                    f"Transactions support **payment date** and **payment type** fields.\n"
                    f"DATEV export is available for sending data to the tax advisor.\n"
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
        """List freelance transaction categories (used for non-SME companies)."""
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]
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
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]

        clients_url = urljoin(config.api_base_url, "api/v1/tax-advisor/clients/")

        try:
            import requests as req
            headers = {
                "Authorization": f"Bearer {api.access_token}",
                "User-Agent": "NormanMCPServer/0.1.0",
                "X-Requested-With": "XMLHttpRequest",
            }
            response = req.get(clients_url, headers=headers, timeout=config.NORMAN_API_TIMEOUT)
            response.raise_for_status()
            clients = response.json()
        except Exception as e:
            return f"Error fetching tax advisor clients: {e}"

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
    async def search_skr_catalog(query: str) -> str:
        """Search the full SKR chart of accounts (SKR03/SKR04) by code or name.
        
        SME only — this resource is for GmbH/UG companies that use a DATEV
        chart of accounts. Returns nothing useful for freelance accounts.
        
        Exposes the complete catalog of ~1000+ account entries, not just the
        categories provisioned for the company.
        
        Args:
            query: Account code prefix (e.g. '42', '6') or name keyword (e.g. 'rent')
        """
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return "No company available. Please authenticate first."

        company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
        company = api._make_request("GET", company_url)
        if not company.get("isSme"):
            return (
                "SKR catalog search is only available for SME companies (GmbH/UG). "
                "The current company is a freelance account."
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
        """List company-specific bookkeeping categories (SME / DATEV chart of accounts).
        
        These are used for GmbH and UG companies that use a DATEV standard chart
        of accounts (SKR03 or SKR04). Each category has a numeric code, name, 
        cashflow type, and optional metadata for amortization rules.
        """
        ctx = mcp.get_context()
        api = ctx.request_context.lifespan_context["api"]
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