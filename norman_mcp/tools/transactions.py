import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from datetime import datetime
from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

ITEMS_TOTAL_TOLERANCE = 0.02


def _build_items_payload(items: List[dict], *, negate: bool) -> List[dict]:
    """Translate positive document lines into the transaction API's signed rows."""
    payload = []
    for order, item in enumerate(items):
        amount = abs(float(item.get("amount") or 0))
        entry: Dict[str, Any] = {
            "description": str(item.get("description") or ""),
            "amount": -amount if negate else amount,
            "vatRate": item.get("vat_rate"),
            "vatType": item.get("vat_type") or "VAT_INCLUDED",
            "order": order,
        }
        if item.get("category_id"):
            entry["category"] = item["category_id"]
        if item.get("company_category_id"):
            entry["companyCategory"] = item["company_category_id"]
        payload.append(entry)
    return payload


def _items_total_mismatch(items: List[dict], amount: float) -> Optional[Dict[str, Any]]:
    items_total = sum(abs(float(item.get("amount") or 0)) for item in items)
    difference = abs(items_total - abs(amount))
    if difference <= ITEMS_TOTAL_TOLERANCE * max(len(items), 1):
        return None
    return {
        "error": (
            f"The line items add up to {items_total:.2f}, but the stated total is "
            f"{abs(amount):.2f}. Re-read the document and fix the complete split."
        ),
    }


def register_transaction_tools(mcp):
    """Register all transaction-related tools with the MCP server."""

    @mcp.tool(
        title="Search Transactions",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def search_transactions(
        ctx: Context,
        description: Optional[str] = Field(
            default=None, description="Text to search for in transaction descriptions"
        ),
        from_date: Optional[str] = Field(
            default=None, description="Start date in YYYY-MM-DD format"
        ),
        to_date: Optional[str] = Field(
            default=None, description="End date in YYYY-MM-DD format"
        ),
        min_amount: Optional[float] = Field(
            default=None, description="Minimum transaction amount"
        ),
        max_amount: Optional[float] = Field(
            default=None, description="Maximum transaction amount"
        ),
        category: Optional[str] = Field(
            default=None, description="Transaction category"
        ),
        no_invoice: Optional[bool] = Field(
            default=None, description="Whether to exclude invoices"
        ),
        no_receipt: Optional[bool] = Field(
            default=None, description="Whether to exclude receipts"
        ),
        status: Optional[str] = Field(
            default=None, description="Status of the transaction (UNVERIFIED, VERIFIED)"
        ),
        cashflow_type: Optional[str] = Field(
            default=None,
            description="Cashflow type of the transaction (INCOME, EXPENSE)",
        ),
        limit: Optional[int] = Field(
            default=None,
            description="Maximum number of results to return (default 100)",
        ),
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
            f"api/v1/companies/{company_id}/accounting/transactions/",
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

        return await api.arequest("GET", transactions_url, params=params)

    @mcp.tool(
        title="Get Transaction",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_transaction(
        ctx: Context,
        transaction_id: str = Field(
            description="Public ID of the transaction to retrieve"
        ),
    ) -> Dict[str, Any]:
        """Get a transaction including its split items and current VAT semantics."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{transaction_id}/",
        )
        return await api.arequest("GET", url)

    @mcp.tool(
        title="Create Transaction",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_transaction(
        ctx: Context,
        amount: float = Field(
            description="Transaction amount (positive for income, negative for expense)"
        ),
        description: str = Field(description="Transaction description"),
        cashflow_type: str = Field(
            description="Cashflow type of the transaction (INCOME, EXPENSE)"
        ),
        supplier_country: str = Field(
            description="Country of the supplier (DE, INSIDE_EU, OUTSIDE_EU)"
        ),
        category_id: Optional[str] = Field(
            default=None,
            description="Freelance category ID (for non-SME companies). If not provided, auto-categorized via AI.",
        ),
        company_category_id: Optional[str] = Field(
            default=None,
            description="SME company category ID from the DATEV chart of accounts (for GmbH/UG companies). Use list_company_categories to find the right ID.",
        ),
        vat_rate: Optional[int] = Field(
            default=None, description="VAT rate (0, 7, 19)"
        ),
        currency: Optional[str] = Field(
            default=None, description="ISO 4217 currency shown on the document"
        ),
        sale_type: Optional[str] = Field(
            default=None, description="Sale type (GOODS, SERVICES)"
        ),
        input_vat_type: Optional[str] = Field(
            default=None,
            description="VAT shown by an EU/non-EU supplier: NO_VAT, GERMAN_VAT or FOREIGN_VAT",
        ),
        reverse_charge: Optional[bool] = Field(
            default=None, description="Whether reverse charge applies"
        ),
        is_refund: bool = Field(
            default=False, description="Whether this reverses a sale or expense"
        ),
        client_id: Optional[str] = Field(
            default=None,
            description="Client public ID for income and EU sales/ZM attribution",
        ),
        vendor_id: Optional[str] = Field(
            default=None,
            description="Vendor public ID for expense and creditor attribution",
        ),
        date: Optional[str] = Field(
            default=None,
            description="Transaction date (document/invoice date) in YYYY-MM-DD format (defaults to today)",
        ),
        payment_date: Optional[str] = Field(
            default=None,
            description="Date when payment was made/received in YYYY-MM-DD format. Used for SME accrual accounting.",
        ),
        payment_type: Optional[str] = Field(
            default=None,
            description="Payment method: BANK, CASH, CREDIT_CARD, PAYPAL or NOT_PAID",
        ),
        ledger_payment_account_code: Optional[str] = Field(
            default=None,
            description="Optional cash/bank/card/PayPal Ledger account override for the payment side",
        ),
        category_metadata: Optional[dict] = Field(
            default=None,
            description="Optional category-specific metadata used by Norman tax and deduction treatments",
        ),
        items: Optional[List[dict]] = Field(
            default=None,
            description=(
                "Complete split lines for documents with multiple categories or VAT rates. "
                "Each line: {description, amount (positive gross), vat_rate, vat_type?, "
                "category_id? or company_category_id?}; lines must sum to the transaction total."
            ),
        ),
    ) -> Dict[str, Any]:
        """
        Create a new manual transaction.

        For SME companies (GmbH/UG), use company_category_id instead of category_id,
        and optionally set payment_date and payment_type for accrual accounting.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if cashflow_type not in ["INCOME", "EXPENSE"]:
            return {"error": "cashflow_type must be either 'INCOME' or 'EXPENSE'"}

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        transactions_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/",
        )

        transaction_data = {
            "amount": abs(amount) if cashflow_type == "INCOME" else -abs(amount),
            "description": description,
            "cashflowType": cashflow_type,
            "valueDate": date,
            "vatRate": vat_rate,
            "saleType": sale_type if sale_type else "",
            "supplierCountry": supplier_country,
            "isRefund": is_refund,
            "company": company_id,
        }

        if category_id:
            transaction_data["category_id"] = category_id
        if company_category_id:
            transaction_data["companyCategory"] = company_category_id
        if payment_date:
            transaction_data["paymentDate"] = payment_date
        if payment_type:
            transaction_data["paymentType"] = payment_type
        if input_vat_type is not None:
            transaction_data["inputVatType"] = input_vat_type
        if reverse_charge is not None:
            transaction_data["reverseCharge"] = reverse_charge
        if client_id:
            transaction_data["client"] = client_id
        if vendor_id:
            transaction_data["vendor"] = vendor_id
        if ledger_payment_account_code:
            transaction_data["ledgerPaymentAccountCode"] = ledger_payment_account_code
        if category_metadata:
            transaction_data["categoryMetadata"] = category_metadata
        if currency:
            transaction_data["currency"] = currency
        if items:
            mismatch = _items_total_mismatch(items, amount)
            if mismatch:
                return mismatch
            transaction_data["items"] = _build_items_payload(
                items,
                negate=cashflow_type == "EXPENSE",
            )
            transaction_data.pop("amount", None)
            transaction_data.pop("vatRate", None)
            transaction_data.pop("category_id", None)
            transaction_data.pop("companyCategory", None)

        return await api.arequest("POST", transactions_url, json_data=transaction_data)

    @mcp.tool(
        title="Update Transaction",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def update_transaction(
        ctx: Context,
        transaction_id: str = Field(
            description="Public ID of the transaction to update"
        ),
        amount: Optional[float] = Field(
            default=None,
            description="Transaction amount (positive for income, negative for expense)",
        ),
        description: Optional[str] = Field(
            default=None, description="Transaction description"
        ),
        category: Optional[str] = Field(
            default=None, description="Freelance category name or ID"
        ),
        date: Optional[str] = Field(
            default=None,
            description="Transaction date (document/invoice date) in YYYY-MM-DD format",
        ),
        vat_rate: Optional[int] = Field(
            default=None, description="VAT rate (0, 7, 19)"
        ),
        currency: Optional[str] = Field(
            default=None, description="ISO 4217 currency shown on the document"
        ),
        sale_type: Optional[str] = Field(
            default=None, description="Sale type (GOODS, SERVICES)"
        ),
        input_vat_type: Optional[str] = Field(
            default=None, description="NO_VAT, GERMAN_VAT or FOREIGN_VAT"
        ),
        reverse_charge: Optional[bool] = Field(
            default=None, description="Whether reverse charge applies"
        ),
        is_refund: Optional[bool] = Field(
            default=None, description="Whether this is a refund/reversal transaction"
        ),
        client_id: Optional[str] = Field(
            default=None, description="Client public ID, or empty string to clear"
        ),
        vendor_id: Optional[str] = Field(
            default=None, description="Vendor public ID, or empty string to clear"
        ),
        supplier_country: Optional[str] = Field(
            default=None,
            description="Country of the supplier (DE, INSIDE_EU, OUTSIDE_EU)",
        ),
        cashflow_type: Optional[str] = Field(
            default=None,
            description="Cashflow type of the transaction (INCOME, EXPENSE)",
        ),
        category_id: Optional[str] = Field(
            default=None, description="Freelance category ID"
        ),
        company_category_id: Optional[str] = Field(
            default=None,
            description="SME company category ID from DATEV chart of accounts (for GmbH/UG)",
        ),
        payment_date: Optional[str] = Field(
            default=None,
            description="Date when payment was made/received in YYYY-MM-DD format",
        ),
        payment_type: Optional[str] = Field(
            default=None,
            description="Payment method: BANK, CASH, CREDIT_CARD, PAYPAL or NOT_PAID",
        ),
        ledger_payment_account_code: Optional[str] = Field(
            default=None, description="Payment-side Ledger account override"
        ),
        category_metadata: Optional[dict] = Field(
            default=None, description="Category-specific tax/deduction metadata"
        ),
        document_not_required: Optional[bool] = Field(
            default=None, description="Whether no receipt/invoice is required"
        ),
        advisor_notes: Optional[str] = Field(
            default=None, description="Private internal accounting note"
        ),
        items: Optional[List[dict]] = Field(
            default=None,
            description=(
                "Replace all split items with this COMPLETE list. Each line contains a positive "
                "gross amount, VAT rate and category; lines must sum to the transaction total."
            ),
        ),
    ) -> Dict[str, Any]:
        """Update an existing transaction. For SME companies, use company_category_id and payment fields."""
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        transaction_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{transaction_id}/",
        )

        update_data = {}
        existing = None
        if items or (amount is not None and cashflow_type is None):
            existing = await api.arequest("GET", transaction_url)
        if items:
            existing_amount = (existing or {}).get("amount")
            try:
                is_expense = float(existing_amount) < 0
            except (TypeError, ValueError):
                is_expense = (existing or {}).get("cashflowType") == "EXPENSE"
            reference_total = amount if amount is not None else existing_amount
            if reference_total is not None:
                try:
                    mismatch = _items_total_mismatch(items, float(reference_total))
                except (TypeError, ValueError):
                    mismatch = None
                if mismatch:
                    return mismatch
            update_data["items"] = _build_items_payload(items, negate=is_expense)
        if amount is not None and not items:
            effective_cashflow_type = cashflow_type or (existing or {}).get(
                "cashflowType"
            )
            update_data["amount"] = (
                abs(amount) if effective_cashflow_type == "INCOME" else -abs(amount)
            )
        if description is not None:
            update_data["description"] = description
        if category is not None and not items:
            update_data["category"] = category
        if date is not None:
            update_data["valueDate"] = date
        if vat_rate is not None and not items:
            update_data["vatRate"] = vat_rate
        if sale_type is not None:
            update_data["saleType"] = sale_type if sale_type else ""
        if supplier_country is not None:
            update_data["supplierCountry"] = supplier_country
        if input_vat_type is not None:
            update_data["inputVatType"] = input_vat_type
        if reverse_charge is not None:
            update_data["reverseCharge"] = reverse_charge
        if is_refund is not None:
            update_data["isRefund"] = is_refund
        if client_id is not None:
            update_data["client"] = client_id or None
        if vendor_id is not None:
            update_data["vendor"] = vendor_id or None
        if cashflow_type is not None:
            update_data["cashflowType"] = cashflow_type
        if category_id is not None and not items:
            update_data["category"] = category_id
        if company_category_id is not None and not items:
            update_data["companyCategory"] = company_category_id
        if payment_date is not None:
            update_data["paymentDate"] = payment_date
        if payment_type is not None:
            update_data["paymentType"] = payment_type
        if ledger_payment_account_code is not None:
            update_data["ledgerPaymentAccountCode"] = ledger_payment_account_code
        if category_metadata is not None:
            update_data["categoryMetadata"] = category_metadata
        if document_not_required is not None:
            update_data["documentNotRequired"] = document_not_required
        if advisor_notes is not None:
            update_data["advisorNotes"] = advisor_notes
        if currency is not None:
            update_data["currency"] = currency

        return await api.arequest("PATCH", transaction_url, json_data=update_data)

    @mcp.tool(
        title="Delete Transaction",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def delete_transaction(
        ctx: Context,
        transaction_id: str = Field(
            description="Public ID of the transaction to delete"
        ),
        confirmed: bool = Field(
            default=False, description="Must be true after explicit user confirmation"
        ),
    ) -> Dict[str, Any]:
        """Delete a transaction and its regenerable Ledger postings after confirmation."""
        if not confirmed:
            return {
                "confirmationRequired": True,
                "warning": "This deletes the transaction and its synthesized Ledger postings.",
            }
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{transaction_id}/",
        )
        return await api.arequest("DELETE", url)

    @mcp.tool(
        title="Categorize Transaction",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def categorize_transaction(
        ctx: Context,
        transaction_amount: float = Field(description="Amount of the transaction"),
        transaction_description: str = Field(
            description="Description of the transaction"
        ),
        transaction_type: str = Field(
            description="Type of transaction (income or expense)"
        ),
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

        detect_url = urljoin(config.api_base_url, "api/v1/assistant/detect-category/")

        request_data = {
            "transaction_amount": transaction_amount,
            "transaction_description": transaction_description,
            "transaction_type": transaction_type,
        }

        return await api.arequest("POST", detect_url, json_data=request_data)

    @mcp.tool(
        title="Change Transaction Verification Status",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def change_transaction_verification(
        ctx: Context,
        transaction_id: str = Field(
            description="Public ID of the transaction to update"
        ),
        verify: bool = Field(
            description="If True, verify (finalize) the transaction; if False, unverify (unfinalize) it"
        ),
    ) -> Dict[str, Any]:
        """
        Verify or unverify a transaction (finalize or unfinalize).

        Args:
            transaction_id: Public ID of the transaction to update
            verify: If True, verify (finalize) the transaction; if False, unverify (unfinalize) it

        Returns:
            Updated transaction information
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id

        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        # Choose the appropriate endpoint based on the verify parameter
        action = "verify" if verify else "unverify"

        transaction_url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{transaction_id}/{action}/",
        )

        return await api.arequest("POST", transaction_url)
