import logging
from decimal import Decimal
from typing import Dict, Any, Optional, List
from typing import Annotated
from urllib.parse import urljoin
from datetime import datetime
from pydantic import Field

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

ITEMS_TOTAL_TOLERANCE = 0.02


ITEM_TAX_FIELDS = {
    "public_id": "publicId", "tax_treatment": "taxTreatment",
    "vat_amount_mode": "vatAmountMode", "vat_document_id": "vatDocumentId",
    "professional_use_part": "professionalUsePart", "metadata": "metadata", "vat_code": "vatCode",
}
ITEM_TAX_DESCRIPTION = (
    " DE GmbH/UG expense items also accept public_id (preserve existing IDs on update), "
    "tax_treatment (null to inherit, DOMESTIC_NO_VAT, DOMESTIC_INPUT_VAT, "
    "DOMESTIC_REVERSE_CHARGE, EU_SERVICE_REVERSE_CHARGE, EU_GOODS_ACQUISITION, "
    "THIRD_COUNTRY_SERVICE_REVERSE_CHARGE), professional_use_part (0..1), "
    "vat_amount_mode (AUTO or DOCUMENTED_GERMAN_INPUT_VAT), documented_vat_amount_eur "
    "(nonnegative decimal string, including zero), vat_document_id (existing company document). "
    "Documented EUR VAT requires DOMESTIC_INPUT_VAT; never use it for reverse charge. "
    "Returning to AUTO requires explicit null documented_vat_amount_eur and vat_document_id. "
    "Read existing items first; omitted fields are preserved by public_id. "
    "Amounts use document orientation: purchases positive, discounts negative; refunds are normalized automatically."
)
CATEGORY_METADATA_DESCRIPTION = (
    "Category-specific tax/deduction metadata. For manual EUR entries of German sole proprietors, "
    "Norman calculates three flat rates from it and replaces the amount (0% VAT, payment type "
    "PRIVATE_CONTRIBUTION): 'Travel meal allowance' {trip_meal_allowance: {trip_start_date, "
    "trip_finish_date, trip_destination (ISO country code), trip_place? (city key from "
    "get_flat_rates), trip_travel_days? (arrival, departure or over 8 hours away), "
    "trip_full_days? (24 hours away)}}, one entry per country; 'Home office flat rate' "
    "{home_office_flat_rate: {home_office_start_date, home_office_finish_date, home_office_days?}}, "
    "which stops at the yearly maximum across entries; 'Private car usage' {car_usage: "
    "{car_use_type (BUSINESS_TRIP or DRIVE_TO_WORK), car_usage_start_date, car_usage_finish_date, "
    "car_usage_distance (km there and back for a trip, one way to work), car_usage_days? "
    "(DRIVE_TO_WORK), car_usage_method (FLAT_RATE calculates, ACTUAL_COSTS keeps the amount)}}. "
    "Keep the dates in one calendar year. Without days, the entry keeps the amount passed. "
    "A depreciable purchase {amortization: {useful_lifetime (months), amortization_method? (straightLine, "
    "or instant for German computer hardware and software: the whole amount in the month of purchase), "
    "professional_use_part? (0 to 1)}} keeps its asset in sync when the amount is above the category's limit."
)
CategoryMetadata = Annotated[dict | None, Field(description=CATEGORY_METADATA_DESCRIPTION)]


def _build_items_payload(items: List[dict], *, negate: bool) -> List[dict]:
    """Normalize the whole document's orientation without erasing discounts."""
    amounts = [Decimal(str(item.get("amount") or 0)) for item in items]
    orientation = Decimal(-1 if negate else 1) * (-1 if sum(amounts) < 0 else 1)
    payload = []
    for order, (item, amount) in enumerate(zip(items, amounts)):
        entry: Dict[str, Any] = {
            "description": str(item.get("description") or ""),
            "amount": float(amount * orientation),
            "vatRate": item.get("vat_rate"),
            "vatType": item.get("vat_type") or "VAT_INCLUDED",
            "order": order,
        }
        if item.get("category_id"):
            entry["category"] = item["category_id"]
        if item.get("company_category_id"):
            entry["companyCategory"] = item["company_category_id"]
        for source, target in ITEM_TAX_FIELDS.items():
            if source in item:
                entry[target] = item[source]
        if "documented_vat_amount_eur" in item:
            value = item["documented_vat_amount_eur"]
            entry["documentedVatAmountEur"] = None if value is None else str(Decimal(str(value)))
        payload.append(entry)
    return payload


def _items_total_mismatch(items: List[dict], amount: float) -> Optional[Dict[str, Any]]:
    items_total = abs(sum((Decimal(str(item.get("amount") or 0)) for item in items), Decimal(0)))
    difference = abs(items_total - abs(Decimal(str(amount))))
    if difference <= Decimal(str(ITEMS_TOTAL_TOLERANCE)) * max(len(items), 1):
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
        description: Optional[str] = Field(default=None, description="Text to search for in transaction descriptions"),
        from_date: Optional[str] = Field(default=None, description="Start date in YYYY-MM-DD format"),
        to_date: Optional[str] = Field(default=None, description="End date in YYYY-MM-DD format"),
        min_amount: Optional[float] = Field(default=None, description="Minimum transaction amount"),
        max_amount: Optional[float] = Field(default=None, description="Maximum transaction amount"),
        category: Optional[str] = Field(default=None, description="Transaction category name"),
        no_invoice: Optional[bool] = Field(default=None, description="Whether to exclude invoices"),
        no_receipt: Optional[bool] = Field(default=None, description="True filters transactions with no primary receipt attached in the database. Use for missing-receipt discovery; no attachment archive scan is needed to establish this state."),
        status: Optional[str] = Field(default=None, description="Status of the transaction (UNVERIFIED, VERIFIED)"),
        cashflow_type: Optional[str] = Field(
            default=None, description="Cashflow type of the transaction (INCOME, EXPENSE)"
        ),
        payment_type: str | None = Field(
            default=None,
            description="Payment type (BANK, CASH, CREDIT_CARD, PAYPAL, NOT_PAID). NOT_PAID lists open bookings.",
        ),
        source: str | None = Field(
            default=None,
            description="Origin: document (booked by Norman from a document), invoice (a Norman invoice's booking), "
            "bank, non_bank",
        ),
        limit: Optional[int] = Field(default=None, ge=1, le=100, description="Results per page (default 20). Use 10 for a targeted lookup."),
        page: int = Field(default=1, ge=1, description="Page number. Follow next pages when the requested scope needs them."),
    ) -> Dict[str, Any]:
        """
        Search for transactions matching specified criteria.

        German companies: an open booking (payment type NOT_PAID) waits for its payment; `openAmount` and
        `payments` say how much is paid. List them with payment_type=NOT_PAID, and the ones Norman booked from
        documents with source=document.

        Args:
            description: Text to search for in transaction descriptions
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            min_amount: Minimum transaction amount
            max_amount: Maximum transaction amount
            category: Transaction category name
            limit: Results per page (default 20)
            page: Page number; keep filters and limit unchanged while paging
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

        transactions_url = urljoin(config.api_base_url, f"api/v1/companies/{company_id}/accounting/transactions/")

        amounts = {"minAmount": min_amount, "maxAmount": max_amount}
        filters = {
            "description": description, "dateFrom": from_date, "dateTo": to_date, "categoryName": category,
            "noInvoice": no_invoice, "noAttachment": no_receipt, "status": status, "cashflowType": cashflow_type,
            "paymentType": payment_type, "source": source,
        }
        params = {name: value for name, value in amounts.items() if value is not None}
        params.update({name: value for name, value in filters.items() if value})
        params["page_size"] = limit or 20
        params["page"] = page

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
        title="Get Flat Rates",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_flat_rates(
        ctx: Context,
        year: int = Field(description="Tax year, e.g. 2026"),
        country: str | None = Field(
            default=None,
            description="ISO country code of a trip destination; omit for every country",
        ),
        exclude_transaction_id: str | None = Field(
            default=None,
            description="Public ID of the home office entry being edited: its own amount does not count as booked",
        ),
    ) -> dict[str, Any]:
        """German official (BMF) flat rates Norman uses for the travel meal allowance and the home office
        flat rate of German sole proprietors; none apply to a Polish company.

        mealAllowance gives per country the fullDay and travelDay rates, and city rates with the key
        to pass as trip_place. homeOffice gives perDay, mostPerYear and what the year's other home
        office entries already use (booked). Null means Norman has no rate for that year.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/flat-rates/",
        )
        params: dict[str, Any] = {"year": year}
        if exclude_transaction_id:
            params["exclude"] = exclude_transaction_id
        rates = await api.arequest("GET", url, params=params)
        meal = rates.get("mealAllowance") if isinstance(rates, dict) else None
        if country and isinstance(meal, dict):
            rates["mealAllowance"] = {country.upper(): meal.get(country.upper())}
        return rates

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
            description="Supplier country: DE or PL for domestic purchases, INSIDE_EU or OUTSIDE_EU for cross-border purchases"
        ),
        category_id: Optional[str] = Field(
            default=None,
            description="Freelance category ID (for non-SME companies). If not provided, auto-categorized via AI.",
        ),
        company_category_id: Optional[str] = Field(
            default=None,
            description="SME company category ID from the selected company chart (DE SKR03/SKR04, PL_KPIR or PL_FULL). Use list_company_categories to find the right ID.",
        ),
        vat_rate: Optional[int] = Field(
            default=None, description="VAT percentage valid for the company country: e.g. PL 23/8/5/0, DE 19/7/0"
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
        vat_code: str | None = Field(
            default=None,
            description=(
                "Polish companies only: the VAT the document states, 23, 8, 5 or 0 (equal to vat_rate), or zw "
                "(exempt), np (supply outside Poland) or oo (reverse charge), which carry vat_rate 0. Read it from "
                "the document; an empty string clears it."
            ),
        ),
        is_refund: bool = Field(
            default=False, description="Whether this reverses a sale or expense"
        ),
        client_id: Optional[str] = Field(
            default=None,
            description="Client public ID for income attribution (and a German company's EU sales in its ZM)",
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
        category_metadata: CategoryMetadata = None,
        items: Optional[List[dict]] = Field(
            default=None,
            description=(
                "Complete split lines for documents with multiple categories or VAT rates. "
                "Each line: {description, amount (positive gross), vat_rate, vat_type?, "
                "category_id? or company_category_id?, vat_code? (PL 23/8/5/0/zw/np/oo)}; lines must sum to the transaction total."
                + ITEM_TAX_DESCRIPTION
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
            "amount": -abs(amount) if (cashflow_type == "EXPENSE") != is_refund else abs(amount),
            "description": description,
            "cashflowType": cashflow_type,
            "valueDate": date,
            "vatRate": vat_rate,
            "saleType": sale_type if sale_type else "",
            "supplierCountry": supplier_country,
            "isRefund": is_refund,
            "company": company_id,
        }

        if vat_code is not None:
            transaction_data["vatCode"] = vat_code

        if category_id:
            transaction_data["category"] = category_id
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
                negate=(cashflow_type == "EXPENSE") != is_refund,
            )
            transaction_data.pop("amount", None)
            transaction_data.pop("vatRate", None)
            transaction_data.pop("category", None)
            transaction_data.pop("companyCategory", None)

        return await api.arequest("POST", transactions_url, json_data=transaction_data)

    @mcp.tool(
        title="Update Transaction",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
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
            default=None, description="VAT percentage valid for the company country: e.g. PL 23/8/5/0, DE 19/7/0"
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
        vat_code: str | None = Field(
            default=None,
            description=(
                "Polish companies only: the VAT the document states, 23, 8, 5 or 0 (equal to vat_rate), or zw "
                "(exempt), np (supply outside Poland) or oo (reverse charge), which carry vat_rate 0. Read it from "
                "the document; an empty string clears it."
            ),
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
            description="Supplier country: DE or PL for domestic purchases, INSIDE_EU or OUTSIDE_EU for cross-border purchases",
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
            description=(
                "Company category ID from the selected company chart (DE SKR03/SKR04, PL_KPIR or "
                "PL_FULL). Use list_company_categories to find the right ID."
            ),
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
        category_metadata: CategoryMetadata = None,
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
                + ITEM_TAX_DESCRIPTION
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
        if items or amount is not None:
            existing = await api.arequest("GET", transaction_url)
        if items:
            existing_amount = (existing or {}).get("amount")
            try:
                is_expense = float(existing_amount) < 0
            except (TypeError, ValueError):
                is_expense = str((existing or {}).get("cashflowType", "")).upper() == "EXPENSE"
            effective_cashflow = cashflow_type or (existing or {}).get("cashflowType")
            if effective_cashflow:
                effective_refund = is_refund if is_refund is not None else (existing or {}).get("isRefund", False)
                is_expense = (effective_cashflow.upper() == "EXPENSE") != effective_refund
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
                (-abs(amount) if (str(effective_cashflow_type).upper() == "EXPENSE") != (
                    is_refund if is_refund is not None else (existing or {}).get("isRefund", False)
                ) else abs(amount))
            )
        if description is not None:
            update_data["description"] = description
        if category is not None and not items:
            update_data["category"] = category
        if date is not None:
            update_data["valueDate"] = date
        if vat_code is not None:
            update_data["vatCode"] = vat_code
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
        title="Find Same Counterparty Transactions",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def find_same_counterparty_transactions(
        ctx: Context,
        transaction_id: str = Field(
            description="Public ID of the booking whose category is about to change"
        ),
    ) -> Dict[str, Any]:
        """
        Before one booking's category changes: the counterparty's other open bookings still in that category.

        Call it with the booking you recategorize, before you save its new category. It lists the open bookings of
        the same counterparty, direction and current category. `suggested` holds the ids that belong with it: all of
        them, or for PayPal and other payment services only those with the same purpose text. Finalized, split and
        tax-treated bookings and payments that pay a booking are left out; `finalizedCount` says how many finalized
        ones stay as they are. Change the ones the user agrees to with update_transaction. If the new category asks
        for details (trip dates, VAT period, business share, asset lifetime), change only the one booking: those
        details belong to it alone.

        Args:
            transaction_id: Public ID of the booking to recategorize

        Returns:
            counterparty, results (the open bookings), suggested (ids) and finalizedCount
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{transaction_id}/same-counterparty/",
        )
        return await api.arequest("GET", url)

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

    @mcp.tool(
        title="Find Booking Payments",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def find_booking_payments(
        ctx: Context,
        transaction_id: str = Field(description="Public ID of an open booking (payment type NOT_PAID) or of a payment"),
    ) -> Dict[str, Any]:
        """
        German and Polish companies: what may pay an open booking, or what a payment may pay.

        For an open booking (from a document, an invoice or made by hand) it lists the payments that fit, best
        first; for a payment, the open bookings it fits. `automatic` marks the one certain match. Pay with
        pay_booking; a Norman invoice's booking is paid with link_transaction.

        Args:
            transaction_id: Public ID of an open booking or of a payment

        Returns:
            Up to 10 matches with both sides' dates, amounts and descriptions
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{transaction_id}/payment-matches/",
        )
        return await api.arequest("GET", url)

    @mcp.tool(
        title="Pay Booking",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def pay_booking(
        ctx: Context,
        booking_id: str = Field(description="Public ID of the open booking (payment type NOT_PAID)"),
        payment_id: str = Field(description="Public ID of the bank payment that pays it"),
        amount: Optional[float] = Field(
            default=None,
            description="German companies: what the payment pays of the booking, in EUR. Omit it to pay what is "
            "open, at most the payment's amount.",
        ),
    ) -> Dict[str, Any]:
        """
        A payment pays an open booking made from a document or by hand.

        German companies: a payment that pays all of it takes the booking over: one row with the booking's lines,
        document and date, and the bank's day as payment date. A smaller amount pays part; the rest stays open.
        Finalized or locked payments and payments that already book another document are refused. A Norman
        invoice's booking is paid with link_transaction.

        Args:
            booking_id: Public ID of the open booking
            payment_id: Public ID of the payment
            amount: What the payment pays of the booking, in EUR (optional)

        Returns:
            The booking while part of it stays open, else the payment that took it over
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        body: Dict[str, Any] = {"payment": payment_id}
        if amount is not None:
            body["amount"] = str(amount)
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{booking_id}/merge-payment/",
        )
        return await api.arequest("POST", url, json_data=body)

    @mcp.tool(
        title="Record Booking Payment",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def record_booking_payment(
        ctx: Context,
        booking_id: str = Field(description="Public ID of the open booking (payment type NOT_PAID)"),
        paid_on: str = Field(description="Day it was paid, YYYY-MM-DD"),
        method: str = Field(description="How it was paid: CASH, CREDIT_CARD, PAYPAL or BANK (a bank Norman does not see)"),
        amount: Optional[float] = Field(
            default=None, description="What was paid, in EUR. Omit it to pay what is open.",
        ),
    ) -> Dict[str, Any]:
        """
        An open booking paid another way, with cash, a card, PayPal or a bank Norman does not see.

        Norman saves the payment and pays the booking with it in one step, as a bank payment would. A smaller
        amount pays part; the rest stays open. For a payment Norman already has, use pay_booking.

        Args:
            booking_id: Public ID of the open booking
            paid_on: Day it was paid (YYYY-MM-DD)
            method: CASH, CREDIT_CARD, PAYPAL or BANK
            amount: What was paid, in EUR (optional)

        Returns:
            The booking while part of it stays open, else the payment that took it over
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        body: Dict[str, Any] = {"paidOn": paid_on, "method": method}
        if amount is not None:
            body["amount"] = str(amount)
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{booking_id}/record-payment/",
        )
        return await api.arequest("POST", url, json_data=body)

    @mcp.tool(
        title="Unlink Payment",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def unlink_payment(
        ctx: Context,
        transaction_id: str = Field(description="Public ID of the payment"),
    ) -> Dict[str, Any]:
        """
        Undo what a payment pays and take its document off it.

        The bookings it paid open again; a booking it took over comes back with its document. A booking Norman
        made from its document cannot be unlinked (delete the booking instead); a Norman invoice's booking is
        undone by cancelling the invoice.

        Args:
            transaction_id: Public ID of the payment

        Returns:
            The payment after the unlink
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/{transaction_id}/unlink/",
        )
        return await api.arequest("POST", url)

    @mcp.tool(
        title="List CSV Import Jobs",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
        ),
    )
    async def list_csv_import_jobs(
        ctx: Context,
        limit: int = Field(default=20, ge=1, le=50, description="Number of recent CSV imports to return"),
    ) -> Dict[str, Any]:
        """List recent CSV transaction imports for the active company.

        Use this before a bulk correction when the user identifies a batch by
        filename, import time or detected provider. Pass the returned job id to
        rollback_csv_import_transactions; do not approximate an import batch
        by description or by all transactions
        in a calendar year.
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        url = urljoin(
            config.api_base_url,
            f"api/v1/companies/{company_id}/accounting/transactions/csv-imports/",
        )
        return await api.arequest("GET", url, params={"limit": limit})

    @mcp.tool(
        title="Roll Back CSV Import Transactions",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False,
        ),
    )
    async def rollback_csv_import_transactions(
        ctx: Context,
        csv_import_job_id: str = Field(
            pattern="^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
            description="Exact CSV import job id returned by list_csv_import_jobs",
        ),
        dry_run: bool = Field(  # noqa: FBT001 - MCP schema exposes an explicit boolean
            default=True,
            description="Preview deletion and immutable-row counts without changing anything",
        ),
        confirmed: bool = Field(  # noqa: FBT001 - explicit confirmation gate
            default=False,
            description="Must be true only after the user explicitly approves this exact preview",
        ),
        preview_token: str | None = Field(
            default=None,
            description="Signed previewToken returned by the immediately preceding preview",
        ),
    ) -> dict[str, Any]:
        """Preview or roll back transactions from one exact CSV import.

        First identify the batch with list_csv_import_jobs. Call this tool with
        dry_run=true, show the filename, import time, counts and transaction
        sample to the user, and ask for explicit confirmation. Only then call
        again with dry_run=false, confirmed=true and the previewToken returned
        by that preview.

        The API soft-deletes only mutable transactions recorded by that import
        job. Finalized and GoBD-locked rows are reported and never deleted. If
        the import or any transaction changed after preview, the token is
        rejected and a fresh preview is required.
        """
        if not dry_run and (not confirmed or not preview_token):
            return {
                "confirmationRequired": True,
                "warning": (
                    "Preview this exact CSV import, show the result to the user, and obtain "
                    "explicit confirmation before applying with its previewToken."
                ),
            }

        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return {"error": "No company available. Please authenticate first."}

        url = urljoin(
            config.api_base_url,
            (
                f"api/v1/companies/{company_id}/accounting/transactions/"
                f"csv-imports/{csv_import_job_id}/rollback/"
            ),
        )
        body: dict[str, Any] = {
            "dryRun": dry_run,
            "confirmed": confirmed,
        }
        if isinstance(preview_token, str) and preview_token:
            body["previewToken"] = preview_token
        return await api.arequest("POST", url, json_data=body)
