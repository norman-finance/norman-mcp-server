"""Products & Services catalog tools.

A product is a reusable invoice position. An invoice line filled from one is a
copy plus a `productId` reference, so editing or archiving a product never
changes an existing invoice.
"""

import logging
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from mcp.types import ToolAnnotations
from norman_mcp import config
from norman_mcp.context import Context

logger = logging.getLogger(__name__)

PRODUCT_TYPES = ("SERVICES", "GOODS")
PRODUCT_STATUSES = ("active", "archived")
UNITS = ("items", "hours", "days", "kilograms", "liters", "meters", "square_meters")
NO_COMPANY = {"error": "No company available. Please authenticate first."}


def _products_url(company_id: str, product_id: Optional[str] = None) -> str:
    path = f"api/v1/companies/{company_id}/products/"
    if product_id:
        path += f"{product_id}/"
    return urljoin(config.api_base_url, path)


def _validation_error(
    product_type: Optional[str] = None,
    unit: Optional[str] = None,
    status: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    if product_type is not None and product_type not in PRODUCT_TYPES:
        return {"error": f"product_type must be one of: {', '.join(PRODUCT_TYPES)}"}
    if unit and unit not in UNITS:
        return {"error": f"unit must be one of: {', '.join(UNITS)}"}
    if status is not None and status not in PRODUCT_STATUSES:
        return {"error": f"status must be one of: {', '.join(PRODUCT_STATUSES)}"}
    return None


def register_product_tools(mcp):
    """Register all product-catalog tools with the MCP server."""

    @mcp.tool(
        title="List Products",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_products(
        ctx: Context,
        search: Optional[str] = None,
        product_type: Optional[str] = None,
        status: str = "active",
        unit: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """
        List the company's catalog products and services.

        Use a product's `publicId` as `productId` on an invoice line, and copy its
        `name`, `description`, `unit` and `vatRate` onto the line. For the line's
        `rate` use `priceNet`, or `priceGross` when the invoice is priced with VAT
        included.

        Args:
            search: Free text matched against name, SKU and description
            product_type: "SERVICES" or "GOODS"
            status: "active" (default), "archived" or "all"
            unit: One of items, hours, days, kilograms, liters, meters, square_meters
            page: Page number, starting at 1
            page_size: Products per page

        Returns:
            Paginated products: count, next, previous, results
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY

        error = _validation_error(product_type=product_type, unit=unit)
        if error:
            return error
        if status not in (*PRODUCT_STATUSES, "all"):
            return {"error": "status must be one of: active, archived, all"}

        params: Dict[str, Any] = {"page": page, "pageSize": page_size, "status": status}
        if search:
            params["search"] = search
        if product_type:
            params["type"] = product_type
        if unit:
            params["unit"] = unit

        return await api.arequest("GET", _products_url(company_id), params=params)

    @mcp.tool(
        title="Get Product",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_product(ctx: Context, product_id: str) -> Dict[str, Any]:
        """
        Get one product with its usage (how many invoices and recurring invoices use it).

        Args:
            product_id: ID of the product

        Returns:
            The product record, including `usage`
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY

        return await api.arequest("GET", _products_url(company_id, product_id))

    @mcp.tool(
        title="Create Product",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_product(
        ctx: Context,
        name: str,
        price: int,
        vat_rate: Optional[int] = None,
        product_type: str = "SERVICES",
        unit: Optional[str] = None,
        description: Optional[str] = None,
        is_price_gross: bool = False,
        sku: Optional[str] = None,
        company_category_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a catalog product or service.

        Args:
            name: Product or service name (unique among the company's active products)
            price: Unit price in cents (net unless is_price_gross is True)
            vat_rate: VAT rate in percent (0, 7, 19 in Germany); the country default if omitted
            product_type: "SERVICES" (default) or "GOODS"
            unit: One of items, hours, days, kilograms, liters, meters, square_meters
            description: Optional text printed under the name on invoices (max 500 chars)
            is_price_gross: True when `price` already includes VAT
            sku: Optional article number, unique per company
            company_category_id: Optional bookkeeping (income) category ID

        Returns:
            The created product
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY

        error = _validation_error(product_type=product_type, unit=unit)
        if error:
            return error

        product_data: Dict[str, Any] = {
            "name": name,
            "price": price,
            "type": product_type,
            "isPriceGross": is_price_gross,
        }
        if vat_rate is not None:
            product_data["vatRate"] = vat_rate
        if unit is not None:
            product_data["unit"] = unit
        if description is not None:
            product_data["description"] = description
        if sku is not None:
            product_data["sku"] = sku
        if company_category_id:
            product_data["companyCategory"] = company_category_id

        return await api.arequest("POST", _products_url(company_id), json_data=product_data)

    @mcp.tool(
        title="Update Product",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def update_product(
        ctx: Context,
        product_id: str,
        name: Optional[str] = None,
        price: Optional[int] = None,
        vat_rate: Optional[int] = None,
        product_type: Optional[str] = None,
        unit: Optional[str] = None,
        description: Optional[str] = None,
        is_price_gross: Optional[bool] = None,
        sku: Optional[str] = None,
        company_category_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a product. Only the given fields change; existing invoices are never touched.

        Args:
            product_id: ID of the product
            name: New name
            price: New unit price in cents
            vat_rate: New VAT rate in percent
            product_type: "SERVICES" or "GOODS"
            unit: One of items, hours, days, kilograms, liters, meters, square_meters; "" clears it
            description: New description (max 500 chars)
            is_price_gross: Whether `price` includes VAT
            sku: New article number
            company_category_id: Bookkeeping category ID; "" clears it
            status: "active" restores an archived product, "archived" archives it

        Returns:
            The updated product
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY

        error = _validation_error(product_type=product_type, unit=unit, status=status)
        if error:
            return error

        update_data: Dict[str, Any] = {}
        if name is not None:
            update_data["name"] = name
        if price is not None:
            update_data["price"] = price
        if vat_rate is not None:
            update_data["vatRate"] = vat_rate
        if product_type is not None:
            update_data["type"] = product_type
        if unit is not None:
            update_data["unit"] = unit
        if description is not None:
            update_data["description"] = description
        if is_price_gross is not None:
            update_data["isPriceGross"] = is_price_gross
        if sku is not None:
            update_data["sku"] = sku
        if company_category_id is not None:
            update_data["companyCategory"] = company_category_id or None
        if status is not None:
            update_data["status"] = status

        if not update_data:
            return {"message": "No fields provided for update."}

        return await api.arequest(
            "PATCH", _products_url(company_id, product_id), json_data=update_data
        )

    @mcp.tool(
        title="Archive Product",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def archive_product(ctx: Context, product_id: str) -> Dict[str, Any]:
        """
        Archive a product: it stops being offered for new invoices; existing invoices keep their lines.
        Restore it later with update_product(status="active").

        Args:
            product_id: ID of the product to archive

        Returns:
            Confirmation
        """
        api = ctx.request_context.lifespan_context["api"]
        company_id = api.company_id
        if not company_id:
            return NO_COMPANY

        result = await api.arequest("DELETE", _products_url(company_id, product_id))
        if isinstance(result, dict) and result.get("error"):
            return result
        return {"message": "Product archived.", "productId": product_id}
