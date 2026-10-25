import logging
from typing import Dict, Any, Literal, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from pydantic import Field
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)


def register_bill_tools(mcp):
    """Register bill (PayBill / Eingangsrechnung) tools with the MCP server.

    Bills are incoming supplier invoices. Backend routes live under the accounting
    namespace: ``api/v1/accounting/bills/``. The API client sends the active
    company in the ``X-Company-Id`` header.

    Bills can be recorded directly or imported through Norman's email inbox.
    Recording or scanning a bill does not initiate a payment.
    """

    @mcp.tool(
        title="List Bills",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_bills(
        ctx: Context,
        status: Optional[str] = None,
        limit: Optional[int] = Field(default=None, ge=1, le=100, description="Page size; omit for the API default"),
        page: int = Field(default=1, ge=1, description="Page number, starting at 1"),
    ) -> Dict[str, Any]:
        """
        Get a list of bills (incoming supplier invoices / Eingangsrechnungen).

        Args:
            status: Optional status filter: DRAFT, PENDING, SCHEDULED, PAID, OVERDUE, CANCELLED
            limit: Maximum number of bills per page
            page: Page to retrieve

        Returns:
            List of bills with their details
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        bills_url = urljoin(config.api_base_url, "api/v1/accounting/bills/")
        params = {"page": page}
        if status:
            params["status"] = status
        if limit is not None:
            params["page_size"] = limit
        return await api.arequest("GET", bills_url, params=params)

    @mcp.tool(
        title="Create Bill",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_bill(
        ctx: Context,
        vendor_name: str = Field(min_length=1, description="Name of the supplier on the bill"),
        amount: float = Field(allow_inf_nan=False, description="Total bill amount in its original currency"),
        currency: str = Field(pattern="^[A-Z]{3}$", description="Currency from the bill, e.g. PLN or EUR; never infer it from the company country"),
        vendor_iban: Optional[str] = None,
        vendor_bic: Optional[str] = None,
        due_date: Optional[str] = Field(default=None, description="Payment due date, YYYY-MM-DD"),
        issue_date: Optional[str] = Field(default=None, description="Invoice issue date, YYYY-MM-DD"),
        reference: Optional[str] = Field(default=None, description="Supplier invoice number"),
        description: Optional[str] = None,
        status: Literal["DRAFT", "PENDING", "SCHEDULED", "PAID", "OVERDUE", "CANCELLED"] = "PENDING",
        vendor_id: Optional[str] = Field(default=None, description="Existing vendor ID in the selected company"),
    ) -> Dict[str, Any]:
        """Record an incoming invoice/payable when the user asks to add a bill.

        Review extracted fields before creating it. This does not send money,
        schedule a bank payment, or file a tax return. A vendor IBAN is optional;
        SEPA payment from Norman is available only for German companies.
        Use list_bills first to avoid recording the same invoice twice.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        payload = {"vendor_name": vendor_name, "amount": str(amount), "currency": currency, "status": status}
        for key, value in {
            "vendor_iban": vendor_iban, "vendor_bic": vendor_bic,
            "due_date": due_date, "issue_date": issue_date,
            "reference": reference, "description": description, "vendor_id": vendor_id,
        }.items():
            if value is not None:
                payload[key] = value
        url = urljoin(config.api_base_url, "api/v1/accounting/bills/")
        return await api.arequest("POST", url, json_data=payload)

    @mcp.tool(
        title="Scan Bill Document",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def scan_bill_document(
        ctx: Context,
        attachment_id: str = Field(min_length=1, description="Uploaded attachment public ID from list_attachments or the upload response"),
    ) -> Dict[str, Any]:
        """Extract supplier, amount, currency, dates and bank details from a document.

        The document must belong to the selected company. Norman uses its OCR
        provider to read it. Returns suggested fields for review; does not create
        a bill or initiate a payment. Use create_bill only after reviewing them.
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}
        url = urljoin(config.api_base_url, "api/v1/accounting/bills/scan/")
        return await api.arequest("POST", url, json_data={"attachment_id": attachment_id})

    @mcp.tool(
        title="Get Bill Details",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_bill(
        ctx: Context,
        bill_id: str
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific bill.

        Args:
            bill_id: ID of the bill to retrieve

        Returns:
            Detailed bill information
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        bill_url = urljoin(config.api_base_url, f"api/v1/accounting/bills/{bill_id}/")
        return api._make_request("GET", bill_url)

    @mcp.tool(
        title="Update Bill",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def update_bill(
        ctx: Context,
        bill_id: str,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update an existing bill. Currently supports changing the bill status — e.g.
        set ``status="PAID"`` to clear a migrated/already-paid bill from the Bills view.

        Args:
            bill_id: ID of the bill to update
            status: New status (e.g. "PAID")

        Returns:
            Updated bill record
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        bill_url = urljoin(config.api_base_url, f"api/v1/accounting/bills/{bill_id}/")

        update_data: Dict[str, Any] = {}
        if status:
            update_data["status"] = status

        if not update_data:
            current_data = api._make_request("GET", bill_url)
            return {"message": "No fields provided for update.", "bill": current_data}

        return api._make_request("PATCH", bill_url, json_data=update_data)

    @mcp.tool(
        title="Mark Bill as Paid",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def mark_bill_paid(
        ctx: Context,
        bill_id: str
    ) -> Dict[str, Any]:
        """
        Mark a bill as paid (``status="PAID"``) WITHOUT initiating a payment.
        Use this for bills that were already paid outside Norman (e.g. migrated
        bills) to clear them from the Bills view. To actually pay a bill via SEPA,
        use ``pay_bill`` instead (German companies only).

        Args:
            bill_id: ID of the bill to mark paid

        Returns:
            Updated bill record
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        bill_url = urljoin(config.api_base_url, f"api/v1/accounting/bills/{bill_id}/")
        return api._make_request("PATCH", bill_url, json_data={"status": "PAID"})

    @mcp.tool(
        title="Pay Bill (SEPA)",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def pay_bill(
        ctx: Context,
        bill_id: str,
        account_id: str,
        execution_date: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initiate a SEPA payment for a bill. ⚠️ This starts a REAL payment flow.
        Returns a ``paymentOrderId`` and a ``webformUrl`` the user must open to
        authorise the payment with their bank. Does not move money on its own, but
        begins the process — only call when the user has explicitly asked to pay.

        Args:
            bill_id: ID of the bill to pay
            account_id: ID of the bank account to pay from (required by the backend)
            execution_date: Optional payment execution date in YYYY-MM-DD format
            purpose: Optional payment purpose / reference text

        Returns:
            Payment order details including paymentOrderId and webformUrl
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        pay_url = urljoin(config.api_base_url, f"api/v1/accounting/bills/{bill_id}/pay/")
        payload: Dict[str, Any] = {"accountId": account_id}
        if execution_date is not None:
            payload["executionDate"] = execution_date
        if purpose is not None:
            payload["purpose"] = purpose
        return api._make_request("POST", pay_url, json_data=payload)

    @mcp.tool(
        title="Delete Bill",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def delete_bill(
        ctx: Context,
        bill_id: str
    ) -> Dict[str, Any]:
        """
        Delete a bill.

        Args:
            bill_id: ID of the bill to delete

        Returns:
            Confirmation of deletion
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        bill_url = urljoin(config.api_base_url, f"api/v1/accounting/bills/{bill_id}/")
        result = api._make_request("DELETE", bill_url)
        if result is None or result == "" or result == {}:
            return {"message": f"Bill {bill_id} deleted successfully."}
        return result
