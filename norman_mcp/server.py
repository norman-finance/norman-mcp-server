import os
import logging
from typing import Any, Dict, List, Optional, Union
import requests
from urllib.parse import urljoin
from dataclasses import dataclass
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Environment configuration
class Config:
    """Configuration for the Norman MCP server."""
    NORMAN_EMAIL = os.getenv("NORMAN_EMAIL", "")
    NORMAN_PASSWORD = os.getenv("NORMAN_PASSWORD", "")
    NORMAN_ENVIRONMENT = os.getenv("NORMAN_ENVIRONMENT", "production")
    NORMAN_API_TIMEOUT = int(os.getenv("NORMAN_API_TIMEOUT", "100"))
    
    @property
    def api_base_url(self) -> str:
        if self.NORMAN_ENVIRONMENT.lower() == "production":
            return "https://api.norman.finance/"
        else:
            return "https://sandbox.norman.finance/"

config = Config()

@dataclass
class NormanAPI:
    """API client for Norman Finance."""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    company_id: Optional[str] = None
    
    def __post_init__(self):
        """Initialize the API client by authenticating with Norman Finance."""
        if not self.access_token:
            # Check if credentials are available before attempting authentication
            if not config.NORMAN_EMAIL or not config.NORMAN_PASSWORD:
                logger.warning("Norman Finance credentials not set. Please set NORMAN_EMAIL and NORMAN_PASSWORD environment variables.")
                logger.warning("The server will start, but API calls will fail until valid credentials are provided.")
                return
            
            try:
                self.authenticate()
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 400:
                    logger.warning("Failed to authenticate with Norman Finance API: Invalid credentials.")
                    logger.warning("Please check your NORMAN_EMAIL and NORMAN_PASSWORD environment variables.")
                    logger.warning("The server will start, but API calls will fail until valid credentials are provided.")
                else:
                    raise
            
    def authenticate(self) -> None:
        """Authenticate with Norman Finance API and get access token."""
        if not config.NORMAN_EMAIL or not config.NORMAN_PASSWORD:
            raise ValueError("Norman Finance credentials not set. Please set NORMAN_EMAIL and NORMAN_PASSWORD environment variables.")
        
        # Extract username from email (as per instructions)
        username = config.NORMAN_EMAIL.split('@')[0]
        
        auth_url = urljoin(config.api_base_url, "api/v1/auth/token/")
        
        payload = {
            "username": username,
            "email": config.NORMAN_EMAIL,
            "password": config.NORMAN_PASSWORD
        }
        
        try:
            response = requests.post(auth_url, json=payload, timeout=config.NORMAN_API_TIMEOUT)
            response.raise_for_status()
            
            auth_data = response.json()
            self.access_token = auth_data.get("access")
            self.refresh_token = auth_data.get("refresh")
            
            # Get company ID (user typically has only one company)
            self._set_company_id()
            
            logger.info("Successfully authenticated with Norman Finance API")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to authenticate with Norman Finance API: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise
    
    def _set_company_id(self) -> None:
        """Get the company ID for the authenticated user."""
        companies_url = urljoin(config.api_base_url, "api/v1/companies/")
        
        try:
            response = self._make_request("GET", companies_url)
            companies = response.get("results", [])
            
            if not companies:
                logger.warning("No companies found for user")
                return
            
            # Use the first company (as per instructions)
            self.company_id = companies[0].get("publicId")
            logger.info(f"Using company ID: {self.company_id}")
        except Exception as e:
            logger.error(f"Error getting company ID: {str(e)}")
            raise
    
    def _make_request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None, 
                     json_data: Optional[Dict[str, Any]] = None, 
                     files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to the Norman Finance API."""
        if not self.access_token:
            self.authenticate()
            
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                files=files,
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.exceptions.HTTPError as e:
            # Handle token expiration
            if e.response.status_code == 401:
                logger.info("Token expired, refreshing...")
                self.authenticate()
                # Retry the request
                return self._make_request(method, url, params, json_data, files)
            else:
                logger.error(f"HTTP error: {str(e)}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"Response: {e.response.text}")
                raise
        except Exception as e:
            logger.error(f"Error making request to {url}: {str(e)}")
            raise

# Server context manager for startup/shutdown
@asynccontextmanager
async def lifespan(ctx: FastMCP):
    """Context manager for startup/shutdown events."""
    # Setup
    api_client = NormanAPI()
    # Create a context dictionary to yield
    context = {"api": api_client}
    
    yield context
    
    # Cleanup - nothing needed for now

# Create the MCP server
mcp = FastMCP("Norman Finance API", lifespan=lifespan)

# Define resources
@mcp.resource("company://current")
async def get_company() -> str:
    """Get details about a company by ID."""
    ctx = mcp.get_context()
    api = ctx.request_context.lifespan_context["api"]
    
    # If no specific company ID is provided, use the default one
    company_id = api.company_id
    company_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/")
    company_data = api._make_request("GET", company_url)
    
    # Format the company information for display
    company_info = (
        f"# {company_data.get('name', 'Unknown Company')}\n\n"
        f"**Account Type**: {company_data.get('accountType', 'N/A')}\n"
        f"**Activity Start**: {company_data.get('activityStart', 'N/A')}\n"
        f"**VAT ID**: {company_data.get('vatNumber', 'N/A')}\n"
        f"**Tax ID**: {company_data.get('taxNumber', 'N/A')}\n"
        f"**Tax State**: {company_data.get('taxState', 'N/A')}\n"
        f"**Profession**: {company_data.get('profession', 'N/A')}\n"
        f"**Address**: {company_data.get('address', {})} "
        f"{company_data.get('zipCode', '')} "
        f"{company_data.get('city', '')}, "
        f"{company_data.get('countryName', {})}\n"
    )
    
    return company_info

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
    
    # Construct query parameters
 
    params = {
        "page": page,
        "pageSize": page_size
    }
    
    
    return api._make_request("GET", clients_url, params=params)

@mcp.resource("taxes://list/{page}/{page_size}")
async def list_taxes(page: int = 1, page_size: int = 100) -> str:
    """List taxe reports available for the user's company."""
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

# Define tools
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
async def get_company_tax_statistics(ctx: Context) -> Dict[str, Any]:
    """
    Get tax statistics for the company.
    
    Returns:
        Company tax statistics data
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
    
    stats_url = urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/company-tax-statistic/"
    )
    
    return api._make_request("GET", stats_url)


@mcp.tool()
async def get_vat_next_report(ctx: Context) -> Dict[str, Any]:
    """
    Get the VAT amount for the next report period.
    
    Returns:
        VAT next report amount data
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
    
    vat_url = urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/vat-next-report-amount/"
    )
    
    return api._make_request("GET", vat_url)


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
        List of matching transactions
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
    category_id: Optional[str] = None,
    cashflow_type: Optional[str] = None,  # "INCOME" or "EXPENSE"
    vat_rate: Optional[int] = None,
    sale_type: Optional[str] = None,
    date: Optional[str] = None,
    supplier_country: Optional[str] = None,
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
    
    # Use current date if not provided
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
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
async def create_invoice(
    ctx: Context,
    client_id: str,
    items: list[dict],
    client_data: Optional[Dict[str, Any]] = None,
    company_data: Optional[Dict[str, Any]] = None,
    invoice_type: str = "GOODS",
    payment_status: Optional[str] = None,
    status: str = "draft",
    issued: Optional[str] = None,
    delivery_date: Optional[str] = None,
    due_to: Optional[str] = None,
    service_start_date: Optional[str] = None,
    service_end_date: Optional[str] = None,
    currency: str = "EUR",
    currency_exchanged: Optional[str] = None,
    payment_terms: Optional[str] = None,
    notes: Optional[str] = None,
    language: str = "de",
    is_vat_included: bool = True,
    iban: Optional[str] = None,
    bic: Optional[str] = None,
    is_to_send: bool = False,
    bank_name: Optional[str] = None,
    create_qr: bool = True,
    save_client_details: bool = False,
    settings_on_overdue: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a new invoice.
    
    Args:
        client_id: ID of the client for the invoice
        items: List of invoice items, each containing name, quantity, rate, vatRate, etc. Example: [{ "name": "string", "quantity": 0, "rate": 0, "vatRate": 0, "itemPriceNet": 0, "itemPriceGross": 0, "itemVatAmount": 0 }]
        client_data: Optional client details to override stored data. Example: {"name": "string", "address": "string", "city": "string", "zipCode": "string", "country": "DE", "vatNumber": "string", "email": "user@example.com", "phone": "string" }
        company_data: Optional company details to override stored data. Example: { "name": "string", "currency": "string", "address": "string", "zipCode": "string", "city": "string", "country": "DE", "taxState": "bayern", "vatNumber": "string", "taxNumber": "string", "iban": "string", "bic": "string", "bankName": "string" }
        invoice_type: Type of invoice (GOODS, SERVICES)
        payment_status: Payment status of the invoice (paid, unpaid)
        status: Invoice status (draft, sent, pending, overdue, uncollectible, saved, sent)
        issued: Issue date in YYYY-MM-DD format
        delivery_date: Delivery date in YYYY-MM-DD format
        due_to: Due date in YYYY-MM-DD format
        service_start_date: Service period start date
        service_end_date: Service period end date
        currency: Invoice currency (default EUR)
        currency_exchanged: Exchange rate information (EUR, USD, etc.)
        payment_terms: Payment terms text
        notes: Additional notes
        language: Invoice language (default 'de')
        is_vat_included: Whether prices include VAT
        iban: IBAN for payments
        bic: BIC/SWIFT code
        is_to_send: Whether to send invoice automatically to client
        bank_name: Name of the bank
        create_qr: Whether to create QR code
        save_client_details: Whether to save updated client details
        settings_on_overdue: Configuration for overdue notifications. Example: { "isToAutosendNotification": false, "notifyAfterDays": [ 0 ], "notifyInParticularDays": [ "2025-04-16" ], "customEmailBody": "string", "customEmailSubject": "string" }
        
    Returns:
        Information about the created invoice
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
    
    # Use current date if not provided
    if not issued:
        issued = datetime.now().strftime("%Y-%m-%d")
    
    invoices_url = urljoin(
        config.api_base_url, 
        f"api/v1/companies/{company_id}/invoices/"
    )
    
    # Get next invoice number if not provided
    next_invoice_url = urljoin(
        config.api_base_url, 
        f"api/v1/companies/{company_id}/invoices/next-number/"
    )
    next_invoice_data = api._make_request("POST", next_invoice_url)
    invoice_number = next_invoice_data.get("nextInvoiceNumber")
    
    # Prepare invoice data
    invoice_data = {
        "client": client_id,
        "invoicedItems": items,
        "invoiceType": invoice_type,
        "invoiceNumber": invoice_number,
        "status": status,
        "issued": issued,
        "currency": currency,
        "isVatIncluded": is_vat_included,
        "language": language,
        "createQr": create_qr,
        "saveClientDetails": save_client_details
    }
    
    # Add optional fields if provided
    if client_data:
        invoice_data["clientData"] = client_data
    if company_data:
        invoice_data["companyData"] = company_data
    if payment_status:
        invoice_data["paymentStatus"] = payment_status
    if delivery_date:
        invoice_data["deliveryDate"] = delivery_date
    if due_to:
        invoice_data["dueTo"] = due_to
    if service_start_date:
        invoice_data["serviceStartDate"] = service_start_date
    if service_end_date:
        invoice_data["serviceEndDate"] = service_end_date
    if currency_exchanged:
        invoice_data["currencyExchanged"] = currency_exchanged
    if payment_terms:
        invoice_data["paymentTerms"] = payment_terms
    if notes:
        invoice_data["notes"] = notes
    if iban:
        invoice_data["iban"] = iban
    if bic:
        invoice_data["bic"] = bic
    if is_to_send:
        invoice_data["isToSend"] = is_to_send
    if bank_name:
        invoice_data["bankName"] = bank_name
    if settings_on_overdue:
        invoice_data["settingsOnOverdue"] = settings_on_overdue
    
    return api._make_request("POST", invoices_url, json_data=invoice_data)

@mcp.tool()
async def get_invoice(
    ctx: Context,
    invoice_id: str
) -> Dict[str, Any]:
    """
    Get detailed information about a specific invoice.
    
    Args:
        invoice_id: ID of the invoice to retrieve
        
    Returns:
        Detailed invoice information
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
    
    invoice_url = urljoin(
        config.api_base_url, 
        f"api/v1/companies/{company_id}/invoices/{invoice_id}/"
    )
    
    return api._make_request("GET", invoice_url)

@mcp.tool()
async def send_invoice(
    ctx: Context,
    invoice_id: str,
    subject: str,
    body: str,
    additional_emails: Optional[List[str]] = None,
    is_send_to_company: bool = False,
    custom_client_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send an invoice via email.
    
    Args:
        invoice_id: ID of the invoice to send
        subject: Email subject line
        body: Email body content
        additional_emails: List of additional email addresses to send to
        is_send_to_company: Whether to send the copy to the company email (Owner)
        custom_client_email: Custom email address for the client (By default the email address of the client is used if it is set)
        
    Returns:
        Response from the send invoice request
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
    
    send_url = urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/invoices/{invoice_id}/send/"
    )
    
    send_data = {
        "subject": subject,
        "body": body,
        "isSendToCompany": is_send_to_company
    }
    
    if additional_emails:
        send_data["additionalEmails"] = additional_emails if additional_emails else []
    if custom_client_email:
        send_data["customClientEmail"] = custom_client_email
        
    return api._make_request("POST", send_url, json_data=send_data)

@mcp.tool() 
async def link_transaction(
    ctx: Context,
    invoice_id: str,
    transaction_id: str
) -> Dict[str, Any]:
    """
    Link a transaction to an invoice.
    
    Args:
        invoice_id: ID of the invoice
        transaction_id: ID of the transaction to link
        
    Returns:
        Response from the link transaction request
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
        
    link_url = urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/invoices/{invoice_id}/link-transaction/"
    )
    
    link_data = {
        "transaction": transaction_id
    }
    
    return api._make_request("POST", link_url, json_data=link_data)

@mcp.tool()
async def get_einvoice_xml(
    ctx: Context,
    invoice_id: str
) -> Dict[str, Any]:
    """
    Get the e-invoice XML for a specific invoice.
    
    Args:
        invoice_id: ID of the invoice to get XML for
        
    Returns:
        E-invoice XML data
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
    
    xml_url = urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/invoices/{invoice_id}/xml/"
    )

    try:
        response = requests.get(
            xml_url,
            headers={"Authorization": f"Bearer {api.access_token}"},
            timeout=config.NORMAN_API_TIMEOUT
        )
        response.raise_for_status()
        
        # Return the XML content as a string
        return {"xml_content": response.text}
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get e-invoice XML: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return {"error": f"Failed to get e-invoice XML: {str(e)}"}


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
    
    client_url = urljoin(
        config.api_base_url, 
        f"api/v1/companies/{company_id}/clients/{client_id}/"
    )
    
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
    
    # Only make the request if there are changes to apply
    if update_data:
        return api._make_request("PATCH", client_url, json_data=update_data)
    else:
        return {"message": "No changes to apply"}

@mcp.tool()
async def upload_bulk_attachments(
    ctx: Context,
    file_paths: List[str],
    cashflow_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Upload multiple file attachments in bulk.
    
    Args:
        file_paths: List of paths to files to upload
        cashflow_type: Optional cashflow type for the transactions (INCOME or EXPENSE)
        
    Returns:
        Response from the bulk upload request
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
        
    upload_url = urljoin(
        config.api_base_url,
        "api/v1/accounting/transactions/upload-documents/"
    )
    
    try:
        files = []
        for path in file_paths:
            with open(path, "rb") as f:
                files.append(("files", f))
                
        data = {}
        if cashflow_type:
            data["cashflow_type"] = cashflow_type
            
        return api._make_request("POST", upload_url, json_data=data, files=files)
    except FileNotFoundError as e:
        return {"error": f"File not found: {str(e)}"}
    except Exception as e:
        return {"error": f"Error uploading files: {str(e)}"}


@mcp.tool()
async def list_attachments(
    ctx: Context,
    file_name: Optional[str] = None,
    linked: Optional[bool] = None,
    attachment_type: Optional[str] = None,
    description: Optional[str] = None,
    brand_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get list of attachments with optional filters.
    
    Args:
        file_name: Filter by file name (case insensitive partial match)
        linked: Filter by whether attachment is linked to transactions
        attachment_type: Filter by attachment type (invoice, receipt, contract, other)
        description: Filter by description (case insensitive partial match)
        brand_name: Filter by brand name (case insensitive partial match)
        
    Returns:
        List of attachments matching the filters
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
        
    attachments_url = urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/attachments/"
    )
    
    params = {}
    if file_name:
        params["file_name"] = file_name
    if linked is not None:
        params["linked"] = linked
    if attachment_type:
        params["has_type"] = attachment_type
    if description:
        params["description"] = description
    if brand_name:
        params["brand_name"] = brand_name
        
    return api._make_request("GET", attachments_url, params=params)

@mcp.tool()
async def create_attachment(
    ctx: Context,
    file_path: str,
    transactions: Optional[List[str]] = None,
    attachment_type: Optional[str] = None,
    amount: Optional[float] = None,
    amount_exchanged: Optional[float] = None,
    attachment_number: Optional[str] = None,
    brand_name: Optional[str] = None,
    currency: str = "EUR",
    currency_exchanged: str = "EUR",
    description: Optional[str] = None,
    supplier_country: Optional[str] = None,
    value_date: Optional[str] = None,
    vat_sum_amount: Optional[float] = None,
    vat_sum_amount_exchanged: Optional[float] = None,
    vat_rate: Optional[int] = None,
    sale_type: Optional[str] = None,
    additional_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a new attachment.
    
    Args:
        file_path: Path to file to upload
        transactions: List of transaction IDs to link
        attachment_type: Type of attachment (invoice, receipt)
        amount: Amount related to attachment
        amount_exchanged: Exchanged amount in different currency
        attachment_number: Unique number for attachment
        brand_name: Brand name associated with attachment
        currency: Currency of amount (default EUR)
        currency_exchanged: Exchanged currency (default EUR)
        description: Description of attachment
        supplier_country: Country of supplier (DE, INSIDE_EU, OUTSIDE_EU)
        value_date: Date of value
        vat_sum_amount: VAT sum amount
        vat_sum_amount_exchanged: Exchanged VAT sum amount
        vat_rate: VAT rate percentage
        sale_type: Type of sale
        additional_metadata: Additional metadata for attachment
        
    Returns:
        Created attachment information
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
        
    attachments_url = urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/attachments/"
    )
    
    try:
        with open(file_path, "rb") as file:
            files = {
                "file": file
            }
            
            data = {}
            if transactions:
                data["transactions"] = transactions
            if attachment_type:
                data["attachment_type"] = attachment_type
            if amount is not None:
                data["amount"] = amount
            if amount_exchanged is not None:
                data["amount_exchanged"] = amount_exchanged
            if attachment_number:
                data["attachment_number"] = attachment_number
            if brand_name:
                data["brand_name"] = brand_name
            if currency:
                data["currency"] = currency
            if currency_exchanged:
                data["currency_exchanged"] = currency_exchanged
            if description:
                data["description"] = description
            if supplier_country:
                data["supplier_country"] = supplier_country
            if value_date:
                data["value_date"] = value_date
            if vat_sum_amount is not None:
                data["vat_sum_amount"] = vat_sum_amount
            if vat_sum_amount_exchanged is not None:
                data["vat_sum_amount_exchanged"] = vat_sum_amount_exchanged
            if vat_rate is not None:
                data["vat_rate"] = vat_rate
            if sale_type:
                data["sale_type"] = sale_type
            if additional_metadata:
                data["additional_metadata"] = additional_metadata
                
            return api._make_request("POST", attachments_url, json_data=data, files=files)
    except FileNotFoundError:
        return {"error": f"File not found: {file_path}"}
    except Exception as e:
        return {"error": f"Error uploading file: {str(e)}"}

@mcp.tool()
async def link_attachment_transaction(
    ctx: Context,
    attachment_id: str,
    transaction_id: str
) -> Dict[str, Any]:
    """
    Link a transaction to an attachment.
    
    Args:
        attachment_id: ID of the attachment
        transaction_id: ID of the transaction to link
        
    Returns:
        Response from the link transaction request
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
        
    link_url = urljoin(
        config.api_base_url,
        f"api/v1/companies/{company_id}/attachments/{attachment_id}/link-transaction/"
    )
    
    link_data = {
        "transaction": transaction_id
    }
    
    return api._make_request("POST", link_url, json_data=link_data)


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


@mcp.tool()
async def list_tax_reports(ctx: Context) -> Dict[str, Any]:
    """List all available tax reports."""
    api = ctx.request_context.lifespan_context["api"]
    
    taxes_url = urljoin(config.api_base_url, "api/v1/taxes/reports/")
    return api._make_request("GET", taxes_url)


@mcp.tool()
async def validate_tax_number(
    ctx: Context,
    tax_number: str,
    region_code: str
) -> Dict[str, Any]:
    """
    Validate a tax number for a specific region.
    
    Args:
        tax_number: Tax number to validate
        region_code: Region code (e.g. "BE" for Belgium)
        
    Returns:
        Validation result for the tax number
    """
    api = ctx.request_context.lifespan_context["api"]
    
    validate_url = urljoin(config.api_base_url, "api/v1/taxes/check-tax-number/")
    
    validation_data = {
        "tax_number": tax_number,
        "region_code": region_code
    }
    
    return api._make_request("POST", validate_url, json_data=validation_data)

@mcp.tool()
async def get_tax_report(
    ctx: Context,
    report_id: str
) -> Dict[str, Any]:
    """
    Retrieve a specific tax report.
    
    Args:
        report_id: Public ID of the tax report to retrieve
        
    Returns:
        Tax report details
    """
    api = ctx.request_context.lifespan_context["api"]
    
    report_url = urljoin(
        config.api_base_url,
        f"api/v1/taxes/reports/{report_id}/"
    )
    
    return api._make_request("GET", report_url)

@mcp.tool()
async def generate_finanzamt_preview(
    ctx: Context,
    report_id: str
) -> Dict[str, Any]:
    """
    Generate a test Finanzamt preview for a tax report.
    
    Args:
        report_id: Public ID of the tax report
        
    Returns:
        Preview data for the tax report
    """
    api = ctx.request_context.lifespan_context["api"]
    
    preview_url = urljoin(
        config.api_base_url,
        f"api/v1/taxes/reports/{report_id}/generate-preview/"
    )
    
    return api._make_request("POST", preview_url)

@mcp.tool()
async def list_tax_states(ctx: Context) -> Dict[str, Any]:
    """
    Get list of available tax states.
    
    Returns:
        List of tax states
    """
    api = ctx.request_context.lifespan_context["api"]
    
    states_url = urljoin(config.api_base_url, "api/v1/taxes/states/")
    
    return api._make_request("GET", states_url)

@mcp.tool()
async def list_tax_settings(ctx: Context) -> Dict[str, Any]:
    """
    Get list of tax settings for the current company.
    
    Returns:
        List of company tax settings
    """
    api = ctx.request_context.lifespan_context["api"]
    
    settings_url = urljoin(config.api_base_url, "api/v1/taxes/tax-settings/")
    
    return api._make_request("GET", settings_url)

@mcp.tool()
async def update_tax_setting(
    ctx: Context,
    setting_id: str,
    tax_type: Optional[str] = None,
    vat_type: Optional[str] = None,
    vat_percent: Optional[float] = None,
    start_tax_report_date: Optional[str] = None,
    reporting_frequency: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a tax setting.
    
    Args:
        setting_id: Public ID of the tax setting to update
        tax_type: Type of tax (e.g. "sales")
        vat_type: VAT type (e.g. "vat_subject")
        vat_percent: VAT percentage
        start_tax_report_date: Start date for tax reporting (YYYY-MM-DD)
        reporting_frequency: Frequency of reporting (e.g. "monthly")
        
    Returns:
        Updated tax setting
    """
    api = ctx.request_context.lifespan_context["api"]
    
    setting_url = urljoin(
        config.api_base_url,
        f"api/v1/taxes/tax-settings/{setting_id}/"
    )
    
    update_data = {}
    if tax_type:
        update_data["taxType"] = tax_type
    if vat_type:
        update_data["vatType"] = vat_type
    if vat_percent is not None:
        update_data["vatPercent"] = vat_percent
    if start_tax_report_date:
        update_data["startTaxReportDate"] = start_tax_report_date
    if reporting_frequency:
        update_data["reportingFrequency"] = reporting_frequency
        
    # Only make request if there are changes
    if update_data:
        return api._make_request("PATCH", setting_url, json_data=update_data)
    else:
        return {"message": "No changes to apply"}


@mcp.tool()
async def list_invoices(
    ctx: Context,
    status: Optional[str] = None,
    name: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = 100
) -> Dict[str, Any]:
    """
    List invoices with optional filtering.
    
    Args:
        status: Filter by invoice status (draft, pending, sent, paid, overdue, uncollectible)
        name: Filter by invoice (client) name
        from_date: Filter invoices created after this date (YYYY-MM-DD)
        to_date: Filter invoices created before this date (YYYY-MM-DD)
        limit: Maximum number of invoices to return (default 100)
        
    Returns:
        List of invoices matching the criteria
    """
    api = ctx.request_context.lifespan_context["api"]
    company_id = api.company_id
    
    if not company_id:
        return {"error": "No company available. Please authenticate first."}
    
    invoices_url = urljoin(
        config.api_base_url, 
        f"api/v1/companies/{company_id}/invoices/"
    )
    
    # Build query parameters
    params = {}
    if status:
        params["status"] = status
    if from_date:
        params["dateFrom"] = from_date
    if to_date:
        params["dateTo"] = to_date
    if limit:
        params["limit"] = limit
    if name:
        params["name"] = name
    
    return api._make_request("GET", invoices_url, params=params)

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
    
    try:
        api._make_request("DELETE", client_url)
        return {"message": f"Client {client_id} deleted successfully"}
    except Exception as e:
        return {"error": f"Failed to delete client: {str(e)}"}

@mcp.prompt()
def create_transaction_prompt(amount: float, description: str, cashflow_type: str = "EXPENSE") -> str:
    """
    Create a prompt for adding a new transaction with essential information.
    
    Args:
        amount: The transaction amount (positive value)
        description: The transaction description
        cashflow_type: Type of transaction (INCOME or EXPENSE)
        
    Returns:
        A formatted prompt for creating a transaction
    """
    # Ensure cashflow_type is valid
    if cashflow_type not in ["INCOME", "EXPENSE"]:
        cashflow_type = "EXPENSE"  # Default to expense
    
    # Format amount sign based on cashflow type
    formatted_amount = amount if cashflow_type == "INCOME" else -amount
    
    return (
        f"Create a new {cashflow_type.lower()} transaction with the following details:\n\n"
        f"Amount: {formatted_amount} EUR\n"
        f"Description: {description}\n\n"
        f"Please confirm the transaction details before submitting. "
        f"You can also add more information such as VAT rate, transaction date, "
        f"or assign a specific category."
    )

@mcp.prompt()
def create_client_prompt(name: str, client_type: str = "business") -> str:
    """
    Create a prompt for adding a new client with basic information.
    
    Args:
        name: The client name or business name
        client_type: Type of client (business or private)
        
    Returns:
        A formatted prompt for creating a client
    """
    # Ensure client_type is valid
    if client_type not in ["business", "private"]:
        client_type = "business"  # Default to business
    
    return (
        f"Create a new {client_type} client with the following details:\n\n"
        f"Name: {name}\n\n"
        f"Please provide additional information about this client such as:\n"
        f"- Email address\n"
        f"- Phone number\n"
        f"- Physical address\n"
        f"- Country\n"
        f"- City and postal code\n"
        f"- VAT number (if applicable)"
    )

@mcp.prompt()
def send_invoice_prompt(invoice_id: str) -> list:
    """
    Create a prompt for sending an invoice via email.
    
    Args:
        invoice_id: ID of the invoice to send
        
    Returns:
        A list of messages forming a conversation about sending an invoice
    """
    from mcp.server.fastmcp.prompts import base
    
    return [
        base.UserMessage(f"I want to send invoice {invoice_id} to the client."),
        base.AssistantMessage("I'll help you send this invoice. What should the email subject line be?"),
        base.UserMessage("Invoice for your recent order"),
        base.AssistantMessage("Great! And what message would you like to include in the email body?"),
        base.UserMessage("Dear Client,\n\nPlease find attached the invoice for your recent order. Payment is due within 14 days.\n\nThank you for your business!\n\nBest regards,"),
        base.AssistantMessage("Would you like to send a copy to yourself or any additional recipients?"),
        base.UserMessage("Yes, please send a copy to myself."),
        base.AssistantMessage("I'll prepare the email with the invoice attachment and send it to the client with a copy to you. Would you like to review the email before sending?")
    ]

@mcp.prompt()
def search_transactions_prompt(date_range: Optional[str] = None) -> str:
    """
    Create a prompt for searching transactions with optional date range.
    
    Args:
        date_range: Optional description of date range (e.g., "last month", "this week")
        
    Returns:
        A formatted prompt for searching transactions
    """
    base_text = "I want to search for transactions"
    
    if date_range:
        base_text += f" from {date_range}"
    
    return (
        f"{base_text}.\n\n"
        f"Please help me find transactions by specifying any of these search criteria:\n"
        f"- Description text to search for\n"
        f"- Specific date range (YYYY-MM-DD format)\n"
        f"- Amount range (minimum and maximum values)\n"
        f"- Transaction category\n"
        f"- Transaction status (VERIFIED, UNVERIFIED)\n"
        f"- Cashflow type (INCOME, EXPENSE)\n"
        f"- Only transactions without invoices or receipts\n\n"
        f"You can combine multiple criteria to narrow down the search results."
    )

if __name__ == "__main__":
    # This will be used by the MCP CLI
    import asyncio
    
    # Use the simpler run method
    mcp.run() 