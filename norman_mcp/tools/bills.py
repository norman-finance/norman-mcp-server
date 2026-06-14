import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)


def register_bill_tools(mcp):
    """Register bill (PayBill / Eingangsrechnung) tools with the MCP server.

    Bills are incoming supplier invoices. Backend routes live under the accounting
    namespace: ``api/v1/accounting/bills/``. The API client adds the active
    ``companyId`` as a query param automatically.

    Note: bills are normally created by Norman's email-import inbox
    (``<handle>@payments.norman.finance``), so this module exposes read / update /
    pay tools rather than a create tool.
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
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get a list of bills (incoming supplier invoices / Eingangsrechnungen).

        Args:
            status: Optional status filter (e.g. "PAID", "OPEN")

        Returns:
            List of bills with their details
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        bills_url = urljoin(config.api_base_url, "api/v1/accounting/bills/")
        params = {"status": status} if status else None
        return api._make_request("GET", bills_url, params=params)

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
        use ``pay_bill`` instead.

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
        bill_id: str
    ) -> Dict[str, Any]:
        """
        Initiate a SEPA payment for a bill. ⚠️ This starts a REAL payment flow.
        Returns a ``paymentOrderId`` and a ``webformUrl`` the user must open to
        authorise the payment with their bank. Does not move money on its own, but
        begins the process — only call when the user has explicitly asked to pay.

        Args:
            bill_id: ID of the bill to pay

        Returns:
            Payment order details including paymentOrderId and webformUrl
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        pay_url = urljoin(config.api_base_url, f"api/v1/accounting/bills/{bill_id}/pay/")
        return api._make_request("POST", pay_url, json_data={})

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
        if result is None or result == "":
            return {"message": f"Bill {bill_id} deleted successfully."}
        return result
