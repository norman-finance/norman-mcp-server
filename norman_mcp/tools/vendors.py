import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)


def register_vendor_tools(mcp):
    """Register all vendor (supplier / Lieferant) tools with the MCP server.

    Vendors are the supplier-side counterpart of clients. Backend routes live under
    the accounting namespace: ``api/v1/accounting/vendors/``. The API client adds the
    active ``companyId`` as a query param automatically.
    """

    @mcp.tool(
        title="List Vendors",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_vendors(
        ctx: Context
    ) -> Dict[str, Any]:
        """
        Get a list of all vendors (suppliers) for the company.

        Returns:
            List of vendors with their details
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        vendors_url = urljoin(config.api_base_url, "api/v1/accounting/vendors/")
        return api._make_request("GET", vendors_url)

    @mcp.tool(
        title="Get Vendor Details",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_vendor(
        ctx: Context,
        vendor_id: str
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific vendor.

        Args:
            vendor_id: ID of the vendor to retrieve

        Returns:
            Detailed vendor information
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        vendor_url = urljoin(config.api_base_url, f"api/v1/accounting/vendors/{vendor_id}/")
        return api._make_request("GET", vendor_url)

    @mcp.tool(
        title="Create Vendor",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_vendor(
        ctx: Context,
        name: str,
        iban: Optional[str] = None,
        bic: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        address: Optional[str] = None,
        country: Optional[str] = None,
        vat_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new vendor (supplier).

        Args:
            name: Vendor name or business name
            iban: Vendor bank account IBAN
            bic: Vendor bank BIC/SWIFT
            email: Vendor email address
            phone: Vendor phone number
            address: Vendor physical address
            country: Vendor country code (e.g. "DE")
            vat_number: Vendor VAT number

        Returns:
            Newly created vendor record
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        vendors_url = urljoin(config.api_base_url, "api/v1/accounting/vendors/")

        vendor_data: Dict[str, Any] = {"name": name}
        if iban:
            vendor_data["iban"] = iban
        if bic:
            vendor_data["bic"] = bic
        if email:
            vendor_data["email"] = email
        if phone:
            vendor_data["phone"] = phone
        if address:
            vendor_data["address"] = address
        if country:
            vendor_data["country"] = country
        if vat_number:
            vendor_data["vatNumber"] = vat_number

        return api._make_request("POST", vendors_url, json_data=vendor_data)

    @mcp.tool(
        title="Update Vendor",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def update_vendor(
        ctx: Context,
        vendor_id: str,
        name: Optional[str] = None,
        iban: Optional[str] = None,
        bic: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        address: Optional[str] = None,
        country: Optional[str] = None,
        vat_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update an existing vendor. Only the fields you pass are changed.

        Args:
            vendor_id: ID of the vendor to update
            name: Updated vendor name
            iban: Updated IBAN
            bic: Updated BIC/SWIFT
            email: Updated email address
            phone: Updated phone number
            address: Updated physical address
            country: Updated country code (e.g. "DE")
            vat_number: Updated VAT number

        Returns:
            Updated vendor record
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        vendor_url = urljoin(config.api_base_url, f"api/v1/accounting/vendors/{vendor_id}/")

        update_data: Dict[str, Any] = {}
        if name:
            update_data["name"] = name
        if iban:
            update_data["iban"] = iban
        if bic:
            update_data["bic"] = bic
        if email:
            update_data["email"] = email
        if phone:
            update_data["phone"] = phone
        if address:
            update_data["address"] = address
        if country:
            update_data["country"] = country
        if vat_number:
            update_data["vatNumber"] = vat_number

        if not update_data:
            current_data = api._make_request("GET", vendor_url)
            return {"message": "No fields provided for update.", "vendor": current_data}

        return api._make_request("PATCH", vendor_url, json_data=update_data)

    @mcp.tool(
        title="Delete Vendor",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def delete_vendor(
        ctx: Context,
        vendor_id: str
    ) -> Dict[str, Any]:
        """
        Delete a vendor.

        Args:
            vendor_id: ID of the vendor to delete

        Returns:
            Confirmation of deletion
        """
        api = ctx.request_context.lifespan_context["api"]
        if not api.company_id:
            return {"error": "No company available. Please authenticate first."}

        vendor_url = urljoin(config.api_base_url, f"api/v1/accounting/vendors/{vendor_id}/")
        result = api._make_request("DELETE", vendor_url)
        if result is None or result == "":
            return {"message": f"Vendor {vendor_id} deleted successfully."}
        return result
