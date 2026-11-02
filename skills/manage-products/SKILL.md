---
name: manage-products
description: Manage the Products & Services catalog - list, create, update, or archive the products and services a company sells, and fill invoice lines from them. Use when the user mentions products, services, a price list, catalog, Artikel, Leistungen, or wants to reuse a position on invoices.
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U0001F4E6"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the user manage the catalog of what they sell:

## Listing and searching
- Call `list_products` (active products by default; `status="archived"` or `"all"` for the rest)
- Present results as a table: Name, Type, Unit, Price (net or gross), VAT rate, SKU

## Creating a product
When creating a product with `create_product`, gather:
- **Required**: name, unit price in cents, and whether the price includes VAT
- **Recommended**: VAT rate (the country default applies if omitted), type (SERVICES or GOODS), unit (items, hours, days, kilograms, liters, meters, square_meters)
- **Optional**: description printed under the name on invoices (max 500 characters), SKU / article number, bookkeeping category
- Names and SKUs are unique among the company's active products

## Using products on invoices
- Find the product with `list_products`, then set `productId` on the invoice item
- Copy the product's name, description, unit and vatRate onto the item; take the rate from `priceNet`, or `priceGross` when the invoice prices include VAT
- The invoice line is a copy: later changes to the product never change existing invoices

## Updating and archiving
- Call `get_product` first to show current values and usage
- Call `update_product` with only the fields that change; confirm with the user before updating
- `archive_product` hides a product from new invoices; existing invoices keep their lines. Restore with `update_product(status="active")`
