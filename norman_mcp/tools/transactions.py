import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from datetime import datetime

from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

def register_transaction_tools(mcp):
    """Register all transaction-related tools with the MCP server."""
    
    @mcp.tool()
    async def search_transactions(
        ctx: Context,
        description: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        category: Optional[str] = None,
        no_invoice: Optional[bool] = False,
        no_receipt: Optional[bool] = False,
        status: Optional[str] = None,
        cashflow_type: Optional[str] = None,
        limit: Optional[int] = 100
    ) -> Dict[str, Any]:
        """
        Search for transactions matching specified criteria.
        
        Args:
            description: Text to search for in transaction descriptions
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            min_amount: Minimum transaction amount
            max_amount: Maximum transaction amount
            category: Transaction category
            limit: Maximum number of results to return (default 100)
            no_invoice: Whether to exclude invoices
            no_receipt: Whether to exclude receipts
            status: Status of the transaction (UNVERIFIED, VERIFIED)
            cashflow_type: Cashflow type of the transaction (INCOME, EXPENSE)
            
        Returns:
            List of matching transactions with sensitive data removed
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        transactions_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/accounting/transactions/"
        )
        
        # Build query parameters
        params = {}
        if description:
            params["description"] = description
        if from_date:
            params["dateFrom"] = from_date
        if to_date:
            params["dateTo"] = to_date
        if min_amount:
            params["minAmount"] = min_amount
        if max_amount:
            params["maxAmount"] = max_amount
        if category:
            params["category_name"] = category
        if no_invoice:
            params["noInvoice"] = no_invoice
        if no_receipt:
            params["noAttachment"] = no_receipt
        if status:
            params["status"] = status
        if cashflow_type:
            params["cashflowType"] = cashflow_type
        if limit:
            params["limit"] = limit
        
        return api._make_request("GET", transactions_url, params=params)

    @mcp.tool()
    async def create_transaction(
        ctx: Context,
        amount: float,
        description: str,
        cashflow_type: str,  # "INCOME" or "EXPENSE"
        supplier_country: str, # DE, INSIDE_EU, OUTSIDE_EU
        category_id: Optional[str] = None,
        vat_rate: Optional[int] = None,
        sale_type: Optional[str] = None,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new manual transaction.
        
        Args:
            amount: Transaction amount (positive for income, negative for expense)
            description: Transaction description
            category: Transaction category
            date: Transaction date in YYYY-MM-DD format (defaults to today)
            vat_rate: VAT rate (0, 7, 19)
            sale_type: Sale type (GOODS, SERVICES)
            supplier_country: Country of the supplier (DE, INSIDE_EU, OUTSIDE_EU)
            cashflow_type: Cashflow type of the transaction (INCOME, EXPENSE)
            category_id: Category ID of the transaction (If not provided, the transaction will be categorized automatically using AI)
            
        Returns:
            Information about the created transaction
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if cashflow_type not in ["INCOME", "EXPENSE"]:
            return {"error": "cashflow_type must be either 'INCOME' or 'EXPENSE'"}
        
        # Use current date if not provided
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        transactions_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/accounting/transactions/"
        )
        
        transaction_data = {
            "amount": abs(amount) if cashflow_type == "INCOME" else -abs(amount),  # Ensure positive amount for expenses
            "description": description,
            "cashflowType": cashflow_type,
            "valueDate": date,
            "vatRate": vat_rate,
            "saleType": sale_type if sale_type else "",
            "supplierCountry": supplier_country,
            "company": company_id
        }
        
        if category_id:
            transaction_data["category_id"] = category_id
        
        return api._make_request("POST", transactions_url, json_data=transaction_data)

    @mcp.tool()
    async def update_transaction(
        ctx: Context,
        transaction_id: str,
        amount: Optional[float] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        date: Optional[str] = None,
        vat_rate: Optional[int] = None,
        sale_type: Optional[str] = None,
        supplier_country: Optional[str] = None,
        cashflow_type: Optional[str] = None,
        category_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing transaction."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        
        transaction_url = urljoin(
            config.api_base_url, 
            f"api/v1/companies/{company_id}/accounting/transactions/{transaction_id}/"
        )
        
        # Prepare update data
        update_data = {}
        if amount is not None:
            update_data["amount"] = abs(amount) if cashflow_type == "INCOME" else -abs(amount)
        if description is not None:
            update_data["description"] = description
        if category is not None:
            update_data["category"] = category
        if date is not None:
            update_data["valueDate"] = date
        if vat_rate is not None:
            update_data["vatRate"] = vat_rate
        if sale_type is not None:
            update_data["saleType"] = sale_type if sale_type else ""
        if supplier_country is not None:
            update_data["supplierCountry"] = supplier_country
        if cashflow_type is not None:
            update_data["cashflowType"] = cashflow_type
        if category_id is not None:
            update_data["category"] = category_id
            
        return api._make_request("PATCH", transaction_url, json_data=update_data)

    @mcp.tool()
    async def categorize_transaction(
        ctx: Context,
        transaction_amount: float,
        transaction_description: str,
        transaction_type: str
    ) -> Dict[str, Any]:
        """
        Detect category for a transaction using AI.
        
        Args:
            transaction_amount: Amount of the transaction
            transaction_description: Description of the transaction
            transaction_type: Type of transaction ("income" or "expense")
            
        Returns:
            Suggested category information for the transaction
        """
        api = ctx.request_context.lifespan_context["api"]
        
        detect_url = urljoin(
            config.api_base_url,
            "api/v1/assistant/detect-category/"
        )
        
        request_data = {
            "transaction_amount": transaction_amount,
            "transaction_description": transaction_description,
            "transaction_type": transaction_type
        }
        
        return api._make_request("POST", detect_url, json_data=request_data) 